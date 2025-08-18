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


def test_cve_queries_positive_and_negative_slices_live(tmp_path):
    driver, database = _get_driver_or_skip()

    with driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

            # Minimal seed: versioned ExternalDependency and a File that depends on it
            session.run(
                """
                CREATE (dep:ExternalDependency {package:'com.example.lib', version:'1.2.3'}),
                       (f:File {path:'src/A.java', total_lines: 200, method_count: 6}),
                       (i:Import {import_path:'com.example.lib.Core'})
                CREATE (i)-[:DEPENDS_ON]->(dep)
                CREATE (f)-[:IMPORTS]->(i)
                CREATE (f)<-[:OF_FILE]-(:FileVer {sha:'abc'})<-[:CHANGED]-(:Commit {date: datetime()})<-[:AUTHORED]-(:Developer {name:'Dev', email:'dev@example.com'})
                """
            ).consume()

            # One CVE that affects the existing versioned dependency
            session.run(
                """
                MATCH (dep:ExternalDependency {package:'com.example.lib'})
                MERGE (c:CVE {id:'CVE-TEST-1'})
                SET c.cvss_score = 8.5
                MERGE (c)-[:AFFECTS]->(dep)
                """
            ).consume()

            # Negative dep without version should not be linked by AFFECTS in our model
            session.run("CREATE (:ExternalDependency {package:'com.example.other'})").consume()

            # Query 1 (FASTEST): should return at least one row
            q1 = (
                "MATCH (cve:CVE) WHERE cve.cvss_score >= 7.0 WITH cve ORDER BY cve.cvss_score DESC LIMIT 50 "
                "MATCH (cve)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File) "
                "WITH cve, dep, collect(DISTINCT f)[0..10] as files UNWIND files as f "
                "MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer) "
                "WITH cve, dep, f, dev, count(DISTINCT c) as commit_count WHERE commit_count >= 1 "
                "RETURN cve.id as vulnerability, dep.package as affected_dependency, f.path as file_path LIMIT 10"
            )
            rows = session.run(q1).data()
            assert rows and any(r["vulnerability"] == "CVE-TEST-1" for r in rows)

            # Query 3 (SUMMARY): with thresholds satisfied by f.total_lines/method_count
            q3 = (
                "MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File) "
                "WHERE cve.cvss_score >= 7.0 AND f.total_lines > 100 AND f.method_count > 5 "
                "RETURN f.path AS file_path, count(DISTINCT cve) AS vulnerability_count"
            )
            rows3 = session.run(q3).data()
            assert rows3 and rows3[0]["vulnerability_count"] >= 1

            # Negative assertion: no AFFECTS to unversioned dependencies
            neg = session.run(
                "MATCH (:CVE)-[:AFFECTS]->(d:ExternalDependency) WHERE d.version IS NULL RETURN count(d) AS c"
            ).single()
            assert neg and int(neg["c"]) == 0
