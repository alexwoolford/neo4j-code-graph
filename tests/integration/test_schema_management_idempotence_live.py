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


def test_ensure_constraints_exist_or_fail_idempotent_live():
    from src.data.schema_management import ensure_constraints_exist_or_fail

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            # First run should create missing schema without error
            ensure_constraints_exist_or_fail(s)
            # Second run should be a no-op without raising
            ensure_constraints_exist_or_fail(s)
            # Spot check a known constraint exists
            rows = s.run(
                "SHOW CONSTRAINTS YIELD name, entityType WHERE entityType='NODE' RETURN count(*) AS c"
            ).single()
            assert rows and int(rows["c"]) >= 1
