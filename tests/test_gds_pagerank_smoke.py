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

    try:
        from src.utils.neo4j_utils import get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")
    uri, username, password, database = get_neo4j_config()

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
