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


def test_cve_deep_dive_experts_and_recent_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                """
                MERGE (dep:ExternalDependency {package:'org.example.experts'})
                MERGE (f:File {path:'src/Deep.java', total_lines: 250, method_count: 7})
                MERGE (i:Import {import_path:'org.example.experts.Api'})
                MERGE (f)-[:IMPORTS]->(i)
                MERGE (i)-[:DEPENDS_ON]->(dep)
                MERGE (cve:CVE {id:'CVE-EXP-1'}) SET cve.cvss_score = 9.0
                MERGE (cve)-[:AFFECTS]->(dep)
                WITH f
                MERGE (fv:FileVer {id:'xv', sha:'sx'})-[:OF_FILE]->(f)
                MERGE (d1:Developer {email:'dev1@example.com', name:'Dev One'})
                MERGE (d2:Developer {email:'dev2@example.com', name:'Dev Two'})
                // Three recent commits by d1, one older commit by d2
                MERGE (c1:Commit {id:'x1', date: datetime() - duration('P10D')})-[:CHANGED]->(fv)
                MERGE (c2:Commit {id:'x2', date: datetime() - duration('P5D')})-[:CHANGED]->(fv)
                MERGE (c3:Commit {id:'x3', date: datetime() - duration('P1D')})-[:CHANGED]->(fv)
                MERGE (c4:Commit {id:'x4', date: datetime() - duration('P200D')})-[:CHANGED]->(fv)
                MERGE (d1)-[:AUTHORED]->(c1)
                MERGE (d1)-[:AUTHORED]->(c2)
                MERGE (d1)-[:AUTHORED]->(c3)
                MERGE (d2)-[:AUTHORED]->(c4)
                """
            ).consume()

            rows = s.run(
                """
                MATCH (cve:CVE {id: 'CVE-EXP-1'})-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
                OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
                WITH f, dep, dev, count(DISTINCT c) as commit_count, max(c.date) as latest_commit
                WITH f, dep,
                     collect(DISTINCT { developer: dev.name, email: dev.email, commits: commit_count, latest_commit: latest_commit }) as developers
                RETURN [d IN developers WHERE d.commits >= 3] as experts,
                       [d IN developers WHERE d.latest_commit > datetime() - duration('P90D')] as recent_contributors
                """
            ).single()
            assert rows is not None
            experts = rows["experts"]
            recent = rows["recent_contributors"]
            assert any(d.get("developer") == "Dev One" for d in experts)
            assert any(d.get("developer") in ("Dev One", "Dev Two") for d in recent)
