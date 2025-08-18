import pytest


@pytest.mark.live
def test_pagerank_via_cypher_live():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")

    with driver:
        with driver.session(database=db) as session:
            # Clear and create a tiny graph
            session.run("MATCH (n) DETACH DELETE n").consume()
            # Schema enforces presence of `method_signature` on :Method
            session.run(
                "CREATE (:Method {id:'A#a():void', name:'A', method_signature:'A#a():void'}), "
                "(:Method {id:'B#b():void', name:'B', method_signature:'B#b():void'}), "
                "(:Method {id:'C#c():void', name:'C', method_signature:'C#c():void'})"
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
