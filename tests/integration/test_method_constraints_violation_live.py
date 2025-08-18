#!/usr/bin/env python3

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


def test_method_signature_uniqueness_violations_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            # Seed one Method
            s.run(
                "CREATE (:Method {id:'p.A#a():void', method_signature:'p.A#a():void', name:'a'})"
            ).consume()

            # Attempt to create a duplicate signature should fail
            with pytest.raises(Exception):
                s.run(
                    "CREATE (:Method {id:'dup', method_signature:'p.A#a():void', name:'a2'})"
                ).consume()

            # Missing method_signature should fail due to required constraint
            with pytest.raises(Exception):
                s.run("CREATE (:Method {id:'no-sig', name:'x'})").consume()
