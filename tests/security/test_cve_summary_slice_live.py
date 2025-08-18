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


def test_cve_summary_slice_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                """
                MERGE (dep:ExternalDependency {package:'org.example.lib'})
                MERGE (f:File {path:'src/Y.java', total_lines: 200, method_count: 6})
                MERGE (i:Import {import_path:'org.example.lib.Api'})
                MERGE (f)-[:IMPORTS]->(i)
                MERGE (i)-[:DEPENDS_ON]->(dep)
                MERGE (cve:CVE {id:'CVE-SUM-1'}) SET cve.cvss_score = 8.7
                MERGE (cve)-[:AFFECTS]->(dep)

                MERGE (fv:FileVer {id:'fv2', sha:'s2'})-[:OF_FILE]->(f)
                MERGE (d:Developer {email:'dev2@example.com', name:'Dev Two'})
                MERGE (c1:Commit {id:'cs1', date: datetime()})-[:CHANGED]->(fv)
                MERGE (d)-[:AUTHORED]->(c1)
                """
            ).consume()

            rows = s.run(
                """
                MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
                WHERE cve.cvss_score >= 7.0 AND f.total_lines > 100 AND f.method_count > 5
                RETURN f.path AS file_path, count(DISTINCT cve) AS vulnerability_count
                """
            ).data()
            assert rows and rows[0]["vulnerability_count"] >= 1
