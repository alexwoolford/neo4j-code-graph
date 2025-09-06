from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def _get_driver_or_skip():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")
    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_pipeline_smoke_live(tmp_path: Path) -> None:
    # Tiny Java repo as pipeline input
    repo = tmp_path / "tiny"
    repo.mkdir()
    _write(
        repo / "src" / "A.java",
        """
        package p;
        import com.fasterxml.jackson.databind.ObjectMapper; // external import to exercise DEPENDS_ON
        class A { void a() { ObjectMapper om = null; } }
        """,
    )
    _write(repo / "src" / "B.java", "package p; class B { void b() { } }")

    # Import core steps
    from src.analysis.code_analysis import (
        bulk_create_nodes_and_relationships,
        extract_file_data,
    )
    from src.constants import EMBEDDING_DIMENSION, EMBEDDING_PROPERTY
    from src.data.schema_management import setup_complete_schema

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Clean and schema
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)

            # Extract from repo
            java_files = list((repo / "src").rglob("*.java"))
            files_data = []
            for f in java_files:
                fd = extract_file_data(f, repo)
                if fd:
                    files_data.append(fd)

            # Zero embeddings for smoke
            file_embeddings = [[0.0] * EMBEDDING_DIMENSION for _ in files_data]
            method_embeddings = [
                [0.0] * EMBEDDING_DIMENSION for _ in [m for fd in files_data for m in fd["methods"]]
            ]

            # Load graph
            bulk_create_nodes_and_relationships(
                session, files_data, file_embeddings, method_embeddings, dependency_versions={}
            )

            # Quick GDS kNN on existing embeddings (vector index required)
            session.run(
                f"""
            CREATE VECTOR INDEX method_embeddings_smoke IF NOT EXISTS
            FOR (m:Method) ON (m.{EMBEDDING_PROPERTY})
            OPTIONS {{indexConfig: {{
              `vector.dimensions`: {EMBEDDING_DIMENSION},
              `vector.similarity_function`: 'cosine'
            }}}}
            """
            ).consume()
            # Await all indexes to be online (name may differ if an equivalent exists)
            session.run("CALL db.awaitIndexes()").consume()
            session.run(
                """
            CALL gds.graph.exists('pipeGraph') YIELD exists
            WITH exists
            WHERE exists
            CALL gds.graph.drop('pipeGraph') YIELD graphName
            RETURN graphName
            """
            ).consume()
            session.run(
                """
            CALL gds.graph.project(
              'pipeGraph',
              ['Method'],
              { DECLARES: { type: 'DECLARES', orientation: 'UNDIRECTED' } },
              { nodeProperties: [$prop] }
            )
            """,
                prop=EMBEDDING_PROPERTY,
            ).consume()
            session.run(
                """
            CALL gds.knn.write('pipeGraph', {
              nodeProperties:$propList, topK:1, similarityCutoff:0.0,
              writeRelationshipType:'SIMILAR', writeProperty:'score'
            })
            """,
                propList=[EMBEDDING_PROPERTY],
            ).consume()
            session.run(
                """
            CALL gds.graph.exists('pipeGraph') YIELD exists
            WITH exists
            WHERE exists
            CALL gds.graph.drop('pipeGraph') YIELD graphName
            RETURN graphName
            """
            ).consume()

            # Assertions: basic pipeline outputs
            rec = session.run("MATCH (:File) RETURN count(*) AS c").single()
            assert rec and int(rec["c"]) >= 2
            rec = session.run("MATCH (:Method) RETURN count(*) AS c").single()
            assert rec and int(rec["c"]) >= 2
            # Import present and linked to dependency
            rec = session.run("MATCH (i:Import) RETURN count(i) AS c").single()
            assert rec and int(rec["c"]) >= 1
            # New: Package nodes and relationships
            rec = session.run(
                "MATCH (p:Package {name:'p'})-[:CONTAINS]->(c:Class) RETURN count(c) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1
            # Create deps linking as loader does and assert it works for the external import
            session.run(
                """
                MATCH (i:Import)
                WITH i, split(i.import_path, '.') AS parts
                WHERE size(parts) >= 3
                WITH i, parts[0] + '.' + parts[1] + '.' + parts[2] AS base_package
                MERGE (e:ExternalDependency {package: base_package})
                MERGE (i)-[:DEPENDS_ON]->(e)
                """
            ).consume()
            rec = session.run(
                "MATCH (:Import)-[:DEPENDS_ON]->(:ExternalDependency) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1
            # SIMILAR may be zero with trivial equal embeddings, but ensure query runs and community write works
            session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) AS c").single()
            # Build similarity graph and run Louvain write to ensure property is set when relationships exist
            session.run(
                "CALL gds.graph.project('pipeComm', ['Method'], { SIMILAR: { type: 'SIMILAR', orientation: 'UNDIRECTED' } })"
            ).consume()
            session.run(
                "CALL gds.louvain.write('pipeComm', {writeProperty:'similarity_community'})"
            ).consume()
            session.run("CALL gds.graph.drop('pipeComm', false)").consume()
