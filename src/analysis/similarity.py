import argparse
import logging
import sys
from time import perf_counter

import pandas as pd
from graphdatascience import GraphDataScience

try:
    # Try absolute import when called from CLI wrapper
    from utils.neo4j_utils import ensure_port, get_neo4j_config
except ImportError:
    # Fallback to relative import when used as module
    from ..utils.neo4j_utils import ensure_port, get_neo4j_config

# Connection settings
NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

EMBEDDING_DIM = 768


logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Create SIMILAR relationships between methods and optionally run "
            "Louvain community detection"
        )
    )
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument("--username", default=NEO4J_USERNAME, help="Neo4j username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Optional log file")
    parser.add_argument("--top-k", type=int, default=5, help="Number of nearest neighbours")
    parser.add_argument("--cutoff", type=float, default=0.8, help="Similarity cutoff")
    parser.add_argument(
        "--no-knn",
        action="store_true",
        help="Skip kNN step and only run community detection",
    )
    parser.add_argument(
        "--no-louvain",
        action="store_true",
        help="Skip Louvain community detection step",
    )
    parser.add_argument(
        "--community-threshold",
        type=float,
        default=0.8,
        help="Minimum SIMILAR score to include when running Louvain",
    )
    parser.add_argument(
        "--community-property",
        default="similarityCommunity",
        help="Property name for Louvain community label",
    )

    return parser.parse_args()


def create_index(gds):
    logger.info("Ensuring vector index exists")
    gds.run_cypher(
        """
        CREATE VECTOR INDEX method_embeddings IF NOT EXISTS
        FOR (m:Method) ON (m.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: $dim,
            `vector.similarity_function`: 'cosine'
        }}
        """,
        params={"dim": EMBEDDING_DIM},
    )
    gds.run_cypher("CALL db.awaitIndex('method_embeddings')")


def run_knn(gds, top_k=5, cutoff=0.8):
    """Run the KNN algorithm and create SIMILAR relationships."""
    base_config = {
        "nodeProperties": "embedding",
        "topK": top_k,
        "similarityCutoff": cutoff,
        "writeRelationshipType": "SIMILAR",
        "writeProperty": "score",
    }

    missing_df = gds.run_cypher(
        "MATCH (m:Method) WHERE m.embedding IS NULL RETURN count(m) AS missing"
    )
    missing = missing_df.iloc[0]["missing"]

    if missing:
        logger.warning("Ignoring %d Method nodes without embeddings", missing)

    graph_name = "methodGraph"
    exists_result = gds.graph.exists(graph_name)
    exists = False
    try:
        if isinstance(exists_result, pd.DataFrame):
            exists = bool(exists_result.loc[0, "exists"])
        elif isinstance(exists_result, pd.Series):
            exists = bool(exists_result.get("exists", False))
        else:
            exists = bool(exists_result)
    except Exception:
        exists = bool(exists_result)

    if exists:
        gds.graph.drop(graph_name)

    graph, _ = gds.graph.project.cypher(
        graph_name,
        (
            "MATCH (m:Method) WHERE m.embedding IS NOT NULL "
            "RETURN id(m) AS id, m.embedding AS embedding"
        ),
        "RETURN null AS source, null AS target LIMIT 0",
    )

    start = perf_counter()
    gds.knn.write(graph, **base_config)
    logger.info(
        "kNN wrote relationships for top %d with cutoff %.2f in %.2fs",
        top_k,
        cutoff,
        perf_counter() - start,
    )
    graph.drop()


def run_louvain(gds, threshold=0.8, community_property="similarityCommunity"):
    """Run Louvain on SIMILAR relationships and write communities."""
    graph_name = "similarityGraph"

    exists_result = gds.graph.exists(graph_name)
    exists = False
    try:
        if isinstance(exists_result, pd.DataFrame):
            exists = bool(exists_result.loc[0, "exists"])
        elif isinstance(exists_result, pd.Series):
            exists = bool(exists_result.get("exists", False))
        else:
            exists = bool(exists_result)
    except Exception:
        exists = bool(exists_result)

    if exists:
        gds.graph.drop(graph_name)

    node_query = "MATCH (m:Method) RETURN id(m) AS id"
    rel_query = (
        "MATCH (m1:Method)-[s:SIMILAR]->(m2:Method) "
        "WHERE s.score >= $threshold "
        "RETURN id(m1) AS source, id(m2) AS target, s.score AS score"
    )

    graph, _ = gds.graph.project.cypher(
        graph_name,
        node_query,
        rel_query,
        parameters={"threshold": threshold},
    )

    start = perf_counter()
    gds.louvain.write(graph, writeProperty=community_property)
    logger.info(
        "Louvain wrote communities to %s using threshold %.2f in %.2fs",
        community_property,
        threshold,
        perf_counter() - start,
    )
    graph.drop()


def main():
    args = parse_args()
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    gds = GraphDataScience(
        ensure_port(args.uri),
        auth=(args.username, args.password),
        database=args.database,
        arrow=False,
    )
    gds.run_cypher("RETURN 1")  # verify connectivity
    logger.info("Connected to Neo4j at %s", ensure_port(args.uri))
    create_index(gds)
    if not args.no_knn:
        run_knn(gds, args.top_k, args.cutoff)
    if not args.no_louvain:
        run_louvain(gds, args.community_threshold, args.community_property)
    gds.close()


if __name__ == "__main__":
    main()
