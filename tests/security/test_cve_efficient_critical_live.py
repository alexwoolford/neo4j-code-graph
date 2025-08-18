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


def test_cve_efficient_developer_grouping_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            # Seed: CVE -> dep <- Import <- File; multiple commits and authors
            s.run(
                """
                MERGE (dep:ExternalDependency {package:'org.example.lib'})
                MERGE (f:File {path:'src/E.java'})
                MERGE (i:Import {import_path:'org.example.lib.Api'})
                MERGE (f)-[:IMPORTS]->(i)
                MERGE (i)-[:DEPENDS_ON]->(dep)
                MERGE (cve:CVE {id:'CVE-EFF', cvss_score:7.2})
                MERGE (cve)-[:AFFECTS]->(dep)
                WITH f
                MERGE (fv:FileVer {id:'efv', sha:'sef'})-[:OF_FILE]->(f)
                MERGE (d1:Developer {email:'a@example.com', name:'A'})
                MERGE (d2:Developer {email:'b@example.com', name:'B'})
                MERGE (c1:Commit {id:'e1', date: datetime()})-[:CHANGED]->(fv)
                MERGE (c2:Commit {id:'e2', date: datetime()})-[:CHANGED]->(fv)
                MERGE (c3:Commit {id:'e3', date: datetime()})-[:CHANGED]->(fv)
                MERGE (d1)-[:AUTHORED]->(c1)
                MERGE (d1)-[:AUTHORED]->(c2)
                MERGE (d2)-[:AUTHORED]->(c3)
                """
            ).consume()

            rows = s.run(
                """
                MATCH (cve:CVE)
                WHERE cve.cvss_score >= 6.0
                WITH cve ORDER BY cve.cvss_score DESC LIMIT 100
                MATCH (cve)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
                MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
                WITH dev,
                     collect(DISTINCT cve.id) as cves,
                     collect(DISTINCT dep.package) as dependencies,
                     collect(DISTINCT f.path) as files,
                     max(cve.cvss_score) as max_severity,
                     count(DISTINCT c) as total_commits
                WHERE total_commits >= 2
                RETURN dev.name as developer, dev.email as email, total_commits as expertise_level
                LIMIT 50
                """
            ).data()
            assert rows and any(r["developer"] == "A" for r in rows)


def test_cve_critical_path_summary_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                """
                MERGE (dep:ExternalDependency {package:'org.example.lib'})
                MERGE (f:File {path:'src/Z.java'})
                MERGE (i:Import {import_path:'org.example.lib.Core'})
                MERGE (f)-[:IMPORTS]->(i)
                MERGE (i)-[:DEPENDS_ON]->(dep)
                MERGE (cve:CVE {id:'CVE-CRIT', cvss_score:9.0})
                MERGE (cve)-[:AFFECTS]->(dep)
                WITH f
                MERGE (fv:FileVer {id:'cfv', sha:'scf'})-[:OF_FILE]->(f)
                MERGE (d:Developer {email:'dev@example.com', name:'Dev'})
                MERGE (c:Commit {id:'cc', date: datetime()})-[:CHANGED]->(fv)
                MERGE (d)-[:AUTHORED]->(c)
                """
            ).consume()

            rows = s.run(
                """
                MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
                WHERE cve.cvss_score >= 8.0
                OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
                WHERE c.date > datetime() - duration('P90D')
                WITH cve.id as cve_id,
                     cve.cvss_score as severity,
                     count(DISTINCT f) as files_affected,
                     count(DISTINCT dev) as developers_involved
                WHERE files_affected > 0
                RETURN cve_id, severity, files_affected, developers_involved
                ORDER BY severity DESC, files_affected DESC
                """
            ).data()
            assert rows and any(
                r["cve_id"] == "CVE-CRIT" and r["files_affected"] >= 1 for r in rows
            )
