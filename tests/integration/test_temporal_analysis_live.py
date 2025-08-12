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


def test_run_coupling_and_hotspots_smoke():
    from src.analysis.temporal_analysis import run_coupling, run_hotspots

    driver, database = _get_driver_or_skip()
    # Create minimal dataset
    with driver.session(database=database) as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
        # Create two files and two commits with co-changes
        session.run("CREATE (:File {path:'A.java'}), (:File {path:'B.java'})").consume()
        session.run(
            """
            CREATE (c1:Commit {sha:'1', date: datetime()})
            CREATE (c2:Commit {sha:'2', date: datetime()})
            WITH c1, c2
            MATCH (a:File {path:'A.java'}), (b:File {path:'B.java'})
            CREATE (c1)-[:CHANGED]->(:FileVer {sha:'1', path:'A.java'})-[:OF_FILE]->(a)
            CREATE (c1)-[:CHANGED]->(:FileVer {sha:'1', path:'B.java'})-[:OF_FILE]->(b)
            CREATE (c2)-[:CHANGED]->(:FileVer {sha:'2', path:'A.java'})-[:OF_FILE]->(a)
            """
        ).consume()

        # Should compute at least one co-change pair and hotspot without raising
        run_coupling(
            driver, database=database, min_support=1, confidence_threshold=0.0, write=False
        )
        run_hotspots(driver, database=database, days=365, min_changes=1, top_n=10, write_back=False)
