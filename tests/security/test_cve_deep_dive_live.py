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


def test_cve_deep_dive_template_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                """
                MERGE (dep:ExternalDependency {package:'org.example.lib'})
                MERGE (f:File {path:'src/DD.java', total_lines: 300, method_count: 8})
                MERGE (i:Import {import_path:'org.example.lib.Api'})
                MERGE (f)-[:IMPORTS]->(i)
                MERGE (i)-[:DEPENDS_ON]->(dep)
                MERGE (cve:CVE {id:'CVE-2022-28291'}) SET cve.cvss_score = 8.1
                MERGE (cve)-[:AFFECTS]->(dep)
                WITH f
                MERGE (fv:FileVer {id:'dfv', sha:'sdf'})-[:OF_FILE]->(f)
                MERGE (d:Developer {email:'dev@example.com', name:'Dev'})
                MERGE (c1:Commit {id:'d1', date: datetime()})-[:CHANGED]->(fv)
                MERGE (c2:Commit {id:'d2', date: datetime()})-[:CHANGED]->(fv)
                MERGE (c3:Commit {id:'d3', date: datetime()})-[:CHANGED]->(fv)
                MERGE (d)-[:AUTHORED]->(c1)
                MERGE (d)-[:AUTHORED]->(c2)
                MERGE (d)-[:AUTHORED]->(c3)
                """
            ).consume()

            rows = s.run(
                """
                MATCH (cve:CVE {id: "CVE-2022-28291"})-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
                OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
                WITH f, dep, dev, count(DISTINCT c) as commit_count, max(c.date) as latest_commit
                WITH f, dep,
                     collect(DISTINCT { developer: dev.name, email: dev.email, commits: commit_count, latest_commit: latest_commit }) as developers
                RETURN f.path as vulnerable_file,
                       f.total_lines as complexity,
                       dep.package as dependency,
                       size(developers) as developer_count,
                       [d IN developers WHERE d.commits >= 3] as experts,
                       [d IN developers WHERE d.latest_commit > datetime() - duration('P90D')] as recent_contributors
                ORDER BY f.total_lines DESC
                """
            ).data()
            assert rows and rows[0]["developer_count"] >= 1
