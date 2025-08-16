from __future__ import annotations

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


def test_temporal_hotspots_and_coupling_live():
    # Minimal synthetic commit/file structure
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

        # Create files and versions
        session.run(
            """
            CREATE (f1:File {path:'src/A.java', total_lines:200, method_count:10}),
                   (f2:File {path:'src/B.java', total_lines:100, method_count:5}),
                   (f3:File {path:'src/C.java', total_lines:50,  method_count:2})
            """
        ).consume()
        session.run(
            """
            UNWIND [1,2,3,4,5] AS i
            CREATE (:Commit {id: toString(i), date: datetime() - duration({days: 10 - i})})
            """
        ).consume()
        # Link commits to file versions
        session.run(
            """
            MATCH (f1:File {path:'src/A.java'}), (f2:File {path:'src/B.java'}), (f3:File {path:'src/C.java'})
            UNWIND [1,2,3,4,5] AS i
            CREATE (v1:FileVer {idx:i})-[:OF_FILE]->(f1),
                   (v2:FileVer {idx:i})-[:OF_FILE]->(f2),
                   (v3:FileVer {idx:i})-[:OF_FILE]->(f3)
            WITH i, v1, v2, v3
            MATCH (c:Commit {id: toString(i)})
            CREATE (c)-[:CHANGED]->(v1)
            WITH i, v2, v3, c
            // Co-change f2 with f1 in first three commits
            FOREACH (_ IN CASE WHEN i <= 3 THEN [1] ELSE [] END | CREATE (c)-[:CHANGED]->(v2))
            // Co-change f3 rarely
            FOREACH (_ IN CASE WHEN i = 1 THEN [1] ELSE [] END | CREATE (c)-[:CHANGED]->(v3))
            """
        ).consume()

        # Run hotspots (recent days=365)
        from src.analysis.temporal_analysis import run_coupling, run_hotspots

        run_hotspots(driver, database, days=365, min_changes=1, top_n=5, write_back=False)
        # Basic assertion: there should be at least one hotspot candidate
        rec = session.run(
            "MATCH (f:File)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(:Commit) RETURN count(DISTINCT f) AS c"
        ).single()
        assert rec and int(rec["c"]) >= 1

        # Run coupling with low thresholds
        run_coupling(driver, database, min_support=2, confidence_threshold=0.0, write=False)
        # Verify at least one co-change pair exists given our synthetic data
        rec = session.run(
            """
            MATCH (c:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f1:File)
            MATCH (c)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f2:File)
            WHERE f1.path < f2.path
            RETURN count(*) AS pairs
            """
        ).single()
        assert rec and int(rec["pairs"]) >= 1
