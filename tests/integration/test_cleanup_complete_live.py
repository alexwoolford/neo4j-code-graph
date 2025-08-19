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


def _count_nodes_and_rels(session):
    n = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    r = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return int(n), int(r)


def test_complete_database_reset_dry_run_then_delete():
    from src.utils.cleanup import complete_database_reset

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()

            # Seed small graph
            s.run("CREATE (:A)-[:R]->(:B)").consume()

            # Create named constraints/indexes expected by reset routine
            s.run(
                "CREATE CONSTRAINT commit_sha IF NOT EXISTS FOR (c:Commit) REQUIRE c.sha IS UNIQUE"
            ).consume()
            s.run(
                "CREATE CONSTRAINT developer_email IF NOT EXISTS FOR (d:Developer) REQUIRE d.email IS UNIQUE"
            ).consume()
            s.run("CREATE INDEX file_path_index IF NOT EXISTS FOR (f:File) ON (f.path)").consume()
            s.run(
                "CREATE INDEX file_ver_composite IF NOT EXISTS FOR (fv:FileVer) ON (fv.sha, fv.path)"
            ).consume()

            n0, r0 = _count_nodes_and_rels(s)
            assert n0 >= 2 and r0 >= 1

            # Dry run should not delete
            complete_database_reset(s, dry_run=True)
            n1, r1 = _count_nodes_and_rels(s)
            assert n1 == n0 and r1 == r0

            # Real delete should clear database (guarded by env)
            import os

            os.environ["CODEGRAPH_ALLOW_RESET"] = "true"
            complete_database_reset(s, dry_run=False)
            os.environ.pop("CODEGRAPH_ALLOW_RESET", None)
            n2, r2 = _count_nodes_and_rels(s)
            assert n2 == 0 and r2 == 0
