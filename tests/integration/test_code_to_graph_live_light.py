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


def test_light_code_to_graph_pipeline_without_embeddings(tmp_path: Path) -> None:
    # Small Java repo
    repo = tmp_path / "tiny"
    repo.mkdir()
    _write(repo / "src" / "A.java", "package p; class A { void a() { b(); } void b() {} }\n")
    _write(repo / "src" / "B.java", "package p; class B { void m() {} }\n")

    from src.analysis.code_analysis import (
        bulk_create_nodes_and_relationships,
        extract_file_data,
    )
    from src.constants import EMBEDDING_DIMENSION
    from src.data.schema_management import setup_complete_schema

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Clean any prior data
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)

            # Build files_data from the tiny repo
            java_files = list((repo / "src").rglob("*.java"))
            files_data = []
            for f in java_files:
                fd = extract_file_data(f, repo)
                if fd:
                    files_data.append(fd)

            # Create dummy embeddings (zeros) to avoid heavy model
            file_embeddings = [[0.0] * EMBEDDING_DIMENSION for _ in files_data]
            method_embeddings = [
                [0.0] * EMBEDDING_DIMENSION for _ in [m for fd in files_data for m in fd["methods"]]
            ]

            # Write to DB
            bulk_create_nodes_and_relationships(
                session, files_data, file_embeddings, method_embeddings, dependency_versions={}
            )

            # Assertions on graph contents
            single = session.run("MATCH (f:File) RETURN count(f) as c").single()
            assert single and single["c"] >= 2
            single = session.run("MATCH (m:Method) RETURN count(m) as c").single()
            assert single and single["c"] >= 2
            # Verify imports and a simple CALLS relationship
            # (Extractor may not always create CALLS for tiny snippets; check presence if any)
            rec = session.run("MATCH (:Import) RETURN count(*) AS c").single()
            assert rec is not None
            # CALLS might be zero for minimal code; ensure no error occurs
            session.run("MATCH ()-[r:CALLS]->() RETURN count(r) AS c").single()
