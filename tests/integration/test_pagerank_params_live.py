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


def test_pagerank_with_configured_iterations_live():
    from src.constants import PAGERANK_ANALYSIS_ITERATIONS

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            # Create a tiny directed CALLS graph: A -> B, A -> C, B -> C so C should rank highest
            session.run(
                """
                CREATE (:Method {id:'A', method_signature:'A#a()', name:'A'}),
                       (:Method {id:'B', method_signature:'B#b()', name:'B'}),
                       (:Method {id:'C', method_signature:'C#c()', name:'C'})
                """
            ).consume()
            session.run(
                "MATCH (a:Method {id:'A'}),(b:Method {id:'B'}),(c:Method {id:'C'}) "
                "CREATE (a)-[:CALLS]->(b), (a)-[:CALLS]->(c), (b)-[:CALLS]->(c)"
            ).consume()

            # Project and run PageRank with configured iterations
            session.run(
                "CALL gds.graph.drop('pr_graph', false) YIELD graphName RETURN graphName"
            ).consume()
            session.run(
                "CALL gds.graph.project('pr_graph', ['Method'], {CALLS: {orientation: 'NATURAL'}})"
            ).consume()
            rows = session.run(
                "CALL gds.pageRank.stream('pr_graph', {maxIterations: $iter}) "
                "YIELD nodeId, score RETURN gds.util.asNode(nodeId).id AS id, score ORDER BY score DESC",
                iter=PAGERANK_ANALYSIS_ITERATIONS,
            ).data()
            assert rows and len(rows) == 3
            # C should be ranked highest given the topology
            assert rows[0]["id"] == "C"
            session.run("CALL gds.graph.drop('pr_graph', false)").consume()
