import os

import pytest


@pytest.mark.live
def test_pagerank_via_cypher_live():
    try:
        from neo4j import GraphDatabase
    except Exception:
        pytest.skip("Neo4j driver not available")

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    pwd = os.getenv("NEO4J_PASSWORD")
    db = os.getenv("NEO4J_DATABASE", "neo4j")

    if not (uri and user and pwd):
        pytest.skip("NEO4J connection not configured for live test")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    with driver:
        with driver.session(database=db) as session:
            # Clear and create a tiny graph
            session.run("MATCH (n) DETACH DELETE n").consume()
            session.run(
                "CREATE (:Method {name:'A'}), (:Method {name:'B'}), (:Method {name:'C'})"
            ).consume()
            session.run(
                "MATCH (a:Method {name:'A'}), (b:Method {name:'B'}), (c:Method {name:'C'}) "
                "CREATE (a)-[:CALLS]->(b), (a)-[:CALLS]->(c), (b)-[:CALLS]->(c)"
            ).consume()

            # Ensure GDS is present then project and run PageRank using Cypher GDS
            session.run("CALL gds.version()").consume()
            session.run("CALL gds.graph.drop('live_pr_graph', false)").consume()
            session.run(
                "CALL gds.graph.project('live_pr_graph', ['Method'], {CALLS: {orientation: 'NATURAL'}})"
            ).consume()
            df = session.run(
                "CALL gds.pageRank.stream('live_pr_graph') YIELD nodeId, score RETURN nodeId, score ORDER BY score DESC"
            ).data()
            assert len(df) >= 1
            session.run("CALL gds.graph.drop('live_pr_graph', false)").consume()
