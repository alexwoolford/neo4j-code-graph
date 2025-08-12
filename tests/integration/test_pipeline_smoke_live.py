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
    _write(repo / "src" / "A.java", "package p; class A { void a() { } }")
    _write(repo / "src" / "B.java", "package p; class B { void b() { } }")

    # Import core steps
    from src.analysis.code_analysis import (
        bulk_create_nodes_and_relationships,
        extract_file_data,
    )
    from src.constants import EMBEDDING_DIMENSION
    from src.data.schema_management import setup_complete_schema

    driver, database = _get_driver_or_skip()
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

        # Quick GDS kNN on any existing embeddings (vector index required)
        session.run(
            """
            CREATE VECTOR INDEX method_embeddings IF NOT EXISTS
            FOR (m:Method) ON (m.embedding)
            OPTIONS {indexConfig: {
              `vector.dimensions`: %d,
              `vector.similarity_function`: 'cosine'
            }}
            """
            % EMBEDDING_DIMENSION
        ).consume()
        session.run("CALL db.awaitIndex('method_embeddings')").consume()
        session.run("CALL gds.graph.drop('pipeGraph', false)").consume()
        session.run(
            """
            CALL gds.graph.project.cypher(
              'pipeGraph',
              'MATCH (m:Method) RETURN id(m) AS id',
              'MATCH (a)-[r:__NONE__]->(b) RETURN id(a) AS source, id(b) AS target',
              { nodeProperties: ['embedding'] }
            )
            """
        ).consume()
        session.run(
            """
            CALL gds.knn.write('pipeGraph', {
              nodeProperties:['embedding'], topK:1, similarityCutoff:0.0,
              writeRelationshipType:'SIMILAR', writeProperty:'score'
            })
            """
        ).consume()
        session.run("CALL gds.graph.drop('pipeGraph', false)").consume()

        # Assertions: basic pipeline outputs
        rec = session.run("MATCH (:File) RETURN count(*) AS c").single()
        assert rec and int(rec["c"]) >= 2
        rec = session.run("MATCH (:Method) RETURN count(*) AS c").single()
        assert rec and int(rec["c"]) >= 2
        # SIMILAR may be zero with trivial equal embeddings, but ensure query runs
        session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) AS c").single()
