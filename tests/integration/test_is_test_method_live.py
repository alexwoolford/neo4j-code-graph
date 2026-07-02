"""Live regression for B6 / A2: methods in src/test/... carry is_test_method=true,
methods in src/main/... carry is_test_method=false. Lets analysts filter
test infrastructure out of centrality / hub queries with one predicate.
"""

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


def test_is_test_method_tagged_from_canonical_test_path(tmp_path: Path) -> None:
    from src.analysis.code_analysis import (
        bulk_create_nodes_and_relationships,
        extract_file_data,
    )
    from src.data.schema_management import setup_complete_schema

    repo = tmp_path / "demo"
    main_dir = repo / "src" / "main" / "java" / "demo"
    test_dir = repo / "src" / "test" / "java" / "demo"
    main_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    (main_dir / "Producer.java").write_text(
        """
        package demo;
        public class Producer {
            public int compute() { return 42; }
        }
        """,
        encoding="utf-8",
    )
    (test_dir / "ProducerTest.java").write_text(
        """
        package demo;
        public class ProducerTest {
            public void testCompute() {
                Producer p = new Producer();
                p.compute();
            }
        }
        """,
        encoding="utf-8",
    )

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            setup_complete_schema(s)
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)

            files_data = []
            for p in repo.rglob("*.java"):
                fd = extract_file_data(p, repo)
                if fd:
                    files_data.append(fd)
            bulk_create_nodes_and_relationships(s, files_data)

            r = s.run(
                """
                MATCH (m:Method)
                RETURN m.class_name AS cls, m.name AS name,
                       m.is_test_method AS is_test
                ORDER BY m.class_name, m.name
                """
            ).data()
            by_method = {(row["cls"], row["name"]): row["is_test"] for row in r}
            assert by_method[("Producer", "compute")] is False
            assert by_method[("ProducerTest", "testCompute")] is True

            # Filter pattern from the cookbook: production-only hub list
            r = s.run(
                """
                MATCH (m:Method)
                WHERE NOT coalesce(m.is_test_method, false)
                RETURN m.class_name AS cls, m.name AS name
                """
            ).data()
            names = {(row["cls"], row["name"]) for row in r}
            assert ("Producer", "compute") in names
            assert ("ProducerTest", "testCompute") not in names
