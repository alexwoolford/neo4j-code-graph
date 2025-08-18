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


def test_progress_reports_counts_live():
    from src.pipeline.progress import check_database_state

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                "CREATE (:File {path:'f.java'}), (:Method {id:'p.C#m():void', name:'m', file:'f.java', line:1, method_signature:'p.C#m():void'}), (:Import {import_path:'java.util.List'})"
            ).consume()
            s.run(
                "MATCH (f:File {path:'f.java'}), (m:Method {name:'m'}) CREATE (f)-[:DECLARES]->(m), (f)-[:IMPORTS]->(:Import {import_path:'java.util.Set'})"
            ).consume()

        state = check_database_state(driver, database)
        assert state["node_types"].get("File", 0) >= 1
        assert state["node_types"].get("Method", 0) >= 1
        assert state["rel_types"].get("IMPORTS", 0) >= 1
