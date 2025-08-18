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


def test_cve_fastest_query_slice_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            # Seed minimal CVE->dep<-File and commits/authors to satisfy the query shape
            s.run(
                """
                MERGE (dep:ExternalDependency {package:'org.example.lib'})
                MERGE (f:File {path:'src/X.java', total_lines: 150, method_count: 10})
                MERGE (i:Import {import_path:'org.example.lib.Core'})
                MERGE (f)-[:IMPORTS]->(i)
                MERGE (i)-[:DEPENDS_ON]->(dep)
                MERGE (cve:CVE {id:'CVE-TEST-FAST'})
                SET cve.cvss_score = 9.1
                MERGE (cve)-[:AFFECTS]->(dep)
                WITH f
                MERGE (fv:FileVer {id:'fv1', sha:'s1'})-[:OF_FILE]->(f)
                MERGE (d:Developer {email:'dev@example.com', name:'Dev One'})
                MERGE (c1:Commit {id:'c1', date: datetime()})-[:CHANGED]->(fv)
                MERGE (c2:Commit {id:'c2', date: datetime()})-[:CHANGED]->(fv)
                MERGE (d)-[:AUTHORED]->(c1)
                MERGE (d)-[:AUTHORED]->(c2)
                """
            ).consume()

            rows = s.run(
                """
                MATCH (cve:CVE)
                WHERE cve.cvss_score >= 7.0
                WITH cve ORDER BY cve.cvss_score DESC LIMIT 50
                MATCH (cve)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
                WITH cve, dep, collect(DISTINCT f)[0..10] as files
                UNWIND files as f
                MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
                WITH cve, dep, f, dev, count(DISTINCT c) as commit_count
                WHERE commit_count >= 1
                RETURN cve.id as vulnerability, dep.package as affected_dependency, f.path as file_path, dev.email as email, commit_count as expertise_level
                LIMIT 100
                """
            ).data()
            assert any(r["vulnerability"] == "CVE-TEST-FAST" for r in rows)
