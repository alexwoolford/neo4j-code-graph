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


def test_cve_deep_dive_multiple_files_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                """
                UNWIND ['src/F1.java','src/F2.java'] AS p
                MERGE (f:File {path:p, total_lines: 120, method_count: 6})
                WITH collect(f) AS files
                MERGE (dep:ExternalDependency {package:'org.example.multi'})
                MERGE (i:Import {import_path:'org.example.multi.Api'})
                WITH files, dep, i
                UNWIND files AS f
                MERGE (f)-[:IMPORTS]->(i)
                MERGE (i)-[:DEPENDS_ON]->(dep)
                WITH collect(f) AS files2, dep
                MERGE (cve:CVE {id:'CVE-MULTI-1'}) SET cve.cvss_score = 8.2
                MERGE (cve)-[:AFFECTS]->(dep)
                WITH files2 AS files
                UNWIND files AS f
                MERGE (v:FileVer {sha: f.path})-[:OF_FILE]->(f)
                MERGE (:Commit {id: f.path, date: datetime()})-[:CHANGED]->(v)
                """
            ).consume()

            rows = s.run(
                """
                MATCH (cve:CVE {id: 'CVE-MULTI-1'})-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
                OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
                WITH f, count(DISTINCT c) AS recent_changes, coalesce(f.method_count,0) AS method_count, coalesce(f.total_lines,0) AS total_lines
                WITH f, recent_changes, method_count, total_lines,
                     (recent_changes * 1.0) + (method_count / 20.0) + (total_lines / 1000.0) AS score
                RETURN f.path AS path, score
                ORDER BY score DESC
                """
            ).data()
            assert rows and len(rows) == 2 and rows[0]["score"] >= rows[1]["score"]
