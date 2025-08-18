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


def test_cleanup_similarities_dry_run_vs_delete_live():
    from src.utils.cleanup import cleanup_similarities

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            # Seed two methods and a SIMILAR edge
            s.run(
                "CREATE (:Method {id:'A', method_signature:'A', name:'a'}), (:Method {id:'B', method_signature:'B', name:'b'})"
            ).consume()
            s.run(
                "MATCH (a:Method {id:'A'}),(b:Method {id:'B'}) CREATE (a)-[:SIMILAR {score:0.9}]->(b) CREATE (b)-[:SIMILAR {score:0.9}]->(a) RETURN 1"
            ).consume()
            pre = s.run("MATCH ()-[r:SIMILAR]-() RETURN count(r) AS c").single()
            if not pre or int(pre["c"]) == 0:
                pytest.skip("Could not seed SIMILAR relationships in this environment")
            # Establish baseline
            before = s.run("MATCH ()-[r:SIMILAR]-() RETURN count(r) AS c").single()
            baseline = int(before["c"]) if before else 0
            assert baseline >= 1
            # Dry run returns 0 by design, but does not delete
            count = cleanup_similarities(s, dry_run=True)
            assert count == 0
            rec = s.run("MATCH ()-[r:SIMILAR]-() RETURN count(r) AS c").single()
            assert rec and int(rec["c"]) == baseline
            # Real delete removes relationships; function may return 0 in some drivers, so rely on post-state
            deleted = cleanup_similarities(s, dry_run=False)
            assert deleted >= 0
            rec = s.run("MATCH ()-[r:SIMILAR]-() RETURN count(r) AS c").single()
            assert rec and int(rec["c"]) == 0
