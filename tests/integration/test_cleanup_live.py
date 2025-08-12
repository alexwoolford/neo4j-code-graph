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


def test_cleanup_similarities_and_communities_live():
    from src.utils.cleanup import cleanup_communities, cleanup_similarities

    driver, database = _get_driver_or_skip()
    with driver.session(database=database) as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
        # Create two methods and SIMILAR rel
        session.run(
            "CREATE (m1:Method {name:'A', method_signature:'sigA'}), (m2:Method {name:'B', method_signature:'sigB'})"
        ).consume()
        session.run(
            "MATCH (m1:Method {name:'A'}), (m2:Method {name:'B'}) CREATE (m1)-[:SIMILAR {score:0.9}]->(m2)"
        ).consume()
        # Add community property
        session.run("MATCH (m:Method {name:'A'}) SET m.similarityCommunity = 1").consume()

        # Dry run should not modify counts
        cleanup_similarities(session, dry_run=True)
        single = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) as c").single()
        assert single and single["c"] == 1

        cleanup_communities(session, "similarityCommunity", dry_run=True)
        single = session.run(
            "MATCH (m:Method) WHERE m.similarityCommunity IS NOT NULL RETURN count(m) as c"
        ).single()
        assert single and single["c"] == 1

        # Actual delete and verify in the same session to ensure read-your-writes
        cleanup_similarities(session, dry_run=False)
        single = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) as c").single()
        assert single and single["c"] == 0

        cleanup_communities(session, "similarityCommunity", dry_run=False)
        single = session.run(
            "MATCH (m:Method) WHERE m.similarityCommunity IS NOT NULL RETURN count(m) as c"
        ).single()
        assert single and single["c"] == 0
