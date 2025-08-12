import pytest


def _get_driver_or_skip():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:  # pragma: no cover
        pytest.skip("Utilities not available")
    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


def test_setup_complete_schema_creates_constraints_and_indexes():
    from src.data.schema_management import setup_complete_schema

    driver, database = _get_driver_or_skip()
    with driver.session(database=database) as session:
        report = setup_complete_schema(session)

        constraints = report.get("constraints", [])
        indexes = report.get("indexes", [])

        # Should have created at least a few core schema items
        def _labels(o):
            x = o.get("labelsOrTypes", [])
            if isinstance(x, list):
                return ",".join(str(v) for v in x)
            return str(x)

        assert any("Method" in _labels(c) for c in constraints)
        assert any("Method" in _labels(i) for i in indexes)
