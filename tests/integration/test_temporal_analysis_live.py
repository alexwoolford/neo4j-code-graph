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


@pytest.mark.live
def test_coupling_and_hotspots_write_back_and_idempotent():
    from src.analysis.temporal_analysis import run_coupling, run_hotspots

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            # Seed two files and commits to produce a single co-change pair
            session.run(
                """
                CREATE (a:File {path:'A.java', total_lines:200, method_count:10}),
                       (b:File {path:'B.java', total_lines:150, method_count:6})
                CREATE (c1:Commit {sha:'c1', date: datetime()}),
                       (c2:Commit {sha:'c2', date: datetime()})
                CREATE (c1)-[:CHANGED]->(:FileVer {sha:'1'})-[:OF_FILE]->(a)
                CREATE (c1)-[:CHANGED]->(:FileVer {sha:'1b'})-[:OF_FILE]->(b)
                CREATE (c2)-[:CHANGED]->(:FileVer {sha:'2'})-[:OF_FILE]->(a)
                """
            ).consume()

        # First run writes back
        run_coupling(driver, database=database, min_support=1, confidence_threshold=0.0, write=True)
        run_hotspots(driver, database=database, days=365, min_changes=1, top_n=10, write_back=True)

        # Verify properties/relationships written
        with driver.session(database=database) as s2:
            cc = s2.run(
                "MATCH (:File {path:'A.java'})-[r:CO_CHANGED]->(:File {path:'B.java'}) RETURN r.support AS s, r.confidence AS c"
            ).single()
            assert cc and float(cc["s"]) >= 1 and float(cc["c"]) >= 0.0
            hs = s2.run(
                "MATCH (f:File {path:'A.java'}) RETURN f.recent_changes AS rc, f.hotspot_score AS hs"
            ).single()
            assert hs and float(hs["rc"]) >= 1 and float(hs["hs"]) > 0.0

        # Second run should be idempotent (no duplicate CO_CHANGED edges)
        run_coupling(driver, database=database, min_support=1, confidence_threshold=0.0, write=True)
        with driver.session(database=database) as s3:
            cnt = s3.run(
                "MATCH (:File {path:'A.java'})-[r:CO_CHANGED]->(:File {path:'B.java'}) RETURN count(r) AS c"
            ).single()
            assert cnt and int(cnt["c"]) == 1
