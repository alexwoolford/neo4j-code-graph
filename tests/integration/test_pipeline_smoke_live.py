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

            # Load graph with explicit dependency versions (strict policy: version required)
            bulk_create_nodes_and_relationships(
                session,
                files_data,
                dependency_versions={
                    "com.fasterxml.jackson.core:jackson-databind:2.15.0": "2.15.0"
                },
            )

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
            # Assert import is linked to a versioned ExternalDependency
            rec = session.run(
                "MATCH (:Import {import_path:'com.fasterxml.jackson.databind.ObjectMapper'})-[:DEPENDS_ON]->(e:ExternalDependency) RETURN count(e) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1
            # Build a CALLS graph and run Louvain write to ensure property is set when relationships exist
            session.run(
                "CALL gds.graph.project('pipeComm', ['Method'], { CALLS: { type: 'CALLS', orientation: 'UNDIRECTED' } })"
            ).consume()
            session.run(
                "CALL gds.louvain.write('pipeComm', {writeProperty:'calls_community'})"
            ).consume()
            session.run(
                "CALL gds.graph.drop('pipeComm', false) YIELD graphName RETURN graphName"
            ).consume()
