import os
import sys
from pathlib import Path

import pytest


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


@pytest.mark.integration
def test_pagerank_smoke_projection_and_stream():
    add_src_to_path()
    try:
        from graphdatascience import GraphDataScience
    except Exception:
        pytest.skip("GDS client not available")

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    if not uri or not username or not password:
        pytest.skip("NEO4J connection not configured for integration test")

    # Support both old and new GDS Python client signatures
    try:
        gds = GraphDataScience(uri, auth=(username, password), database=database)
    except TypeError:
        gds = GraphDataScience(uri, auth=(username, password))
        try:
            # Older clients use set_database
            gds.set_database(database)  # type: ignore[attr-defined]
        except Exception:
            pass

    # Create a tiny graph: A->B, A->C, B->C
    try:
        gds.run_cypher("MATCH (n) DETACH DELETE n")
    except Exception:
        pytest.skip("Neo4j not reachable for GDS test")

    gds.run_cypher(
        """
        CREATE (:Method {name:'A'}), (:Method {name:'B'}), (:Method {name:'C'});
        MATCH (a:Method {name:'A'}), (b:Method {name:'B'}), (c:Method {name:'C'})
        CREATE (a)-[:CALLS]->(b), (a)-[:CALLS]->(c), (b)-[:CALLS]->(c);
        """
    )

    # Project and run PageRank
    G, _meta = gds.graph.project("test_pr_graph", ["Method"], {"CALLS": {"orientation": "NATURAL"}})
    try:
        df = gds.pageRank.stream(G)
        assert not df.empty
    finally:
        gds.graph.drop(G.name())
