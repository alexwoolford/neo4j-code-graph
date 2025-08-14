from __future__ import annotations

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


def test_validate_cypher_queries_live() -> None:
    # Validate a representative set of project Cypher patterns against a real DB
    from src.data.schema_management import setup_complete_schema
    from src.utils.cypher_validation import run_validation

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Fresh DB and schema to avoid interference
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)

            results = run_validation(session)
            # All validations should pass (EXPLAIN-phase only)
            assert results, "Expected validation results"
            assert all(ok for _, ok, _ in results), str(results)
