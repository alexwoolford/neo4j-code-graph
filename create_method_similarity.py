import argparse
import logging
import sys
from time import perf_counter
from graphdatascience import GraphDataScience

from utils import ensure_port, get_neo4j_config

# Connection settings
NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

EMBEDDING_DIM = 768


logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Create SIMILAR relationships between methods"
    )
    parser.add_argument(
        "--uri",
        default=NEO4J_URI,
        help="Neo4j connection URI",
    )
    parser.add_argument(
        "--username",
        default=NEO4J_USERNAME,
        help="Neo4j authentication username",
    )
    parser.add_argument(
        "--password",
        default=NEO4J_PASSWORD,
        help="Neo4j authentication password",
    )
    parser.add_argument(
        "--database",
        default=NEO4J_DATABASE,
        help="Neo4j database to use",
    )
    parser.add_argument(
        "--top-k", type=int, default=5, help="Number of nearest neighbours"
    )
    parser.add_argument("--cutoff", type=float, default=0.8, help="Similarity cutoff")
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument(
        "--log-file",
        help="Write logs to this file as well as the console",
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
    if gds.graph.exists(graph_name):
        gds.graph.drop(graph_name)

    graph, _ = gds.graph.project(
        graph_name,
        {"Method": {"properties": "embedding", "where": "m.embedding IS NOT NULL"}},
        "*",
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
    run_knn(gds, args.top_k, args.cutoff)
    gds.close()


if __name__ == "__main__":
    main()
