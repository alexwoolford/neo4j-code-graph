#!/usr/bin/env python3

import pytest


def _get_driver_or_skip():
    try:
        # Lazy import to avoid hard dependency when not running live
        from src.utils.common import create_neo4j_driver  # type: ignore
        from src.utils.neo4j_utils import get_neo4j_config  # type: ignore
    except Exception:
        pytest.skip("Utilities not available")

    uri, user, pwd, db = get_neo4j_config()
    # If no real connection configured, skip
    if not uri or not user or not pwd:
        pytest.skip("Neo4j not configured for live tests")
    try:
        driver = create_neo4j_driver(uri, user, pwd)
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")
    return driver, db


@pytest.mark.live
def test_required_constraints_exist_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Show constraints and map by name for convenience
            rows = session.run("SHOW CONSTRAINTS").data()
            names = {row.get("name") for row in rows}

            # Method constraints
            assert "method_signature_unique" in names
            assert "method_signature_required" in names
            assert "method_id_required" in names

            # File, Directory, Class, Interface basics (stable set)
            for required in [
                "file_path",
                "directory_path",
                "class_name_file",
                "interface_name_file",
            ]:
                assert required in names


@pytest.mark.live
def test_vector_index_available_for_methods_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            rows = session.run("SHOW INDEXES").data()
            # At least one vector index on Method embeddings should be present
            has_vec = False
            for r in rows:
                if r.get("type") == "VECTOR" and r.get("entityType") == "NODE":
                    if r.get("labelsOrTypes") and "Method" in r.get("labelsOrTypes"):
                        has_vec = True
                        break
            assert has_vec, "Expected a vector index on :Method embeddings"


@pytest.mark.live
def test_schema_guard_recreates_missing_constraint_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Drop one core constraint if present
            rows = session.run("SHOW CONSTRAINTS").data()
            names = {row.get("name") for row in rows}
            if "file_path" in names:
                session.run("DROP CONSTRAINT file_path IF EXISTS").consume()

            # Ensure guard recreates it
            from src.data.schema_management import ensure_constraints_exist_or_fail

            ensure_constraints_exist_or_fail(session)
            rows2 = session.run("SHOW CONSTRAINTS").data()
            names2 = {row.get("name") for row in rows2}
            assert "file_path" in names2
