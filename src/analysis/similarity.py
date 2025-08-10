import argparse
import logging
import os
from time import perf_counter

import pandas as pd
from graphdatascience import GraphDataScience

try:
    # Prefer centralized constants when available
    from src.constants import (
        COMMUNITY_PROPERTY,
        EMBEDDING_DIMENSION,
        SIMILARITY_CUTOFF,
        SIMILARITY_TOP_K,
    )
except Exception:
    # Fallback to defaults if constants import path differs
    from ..constants import COMMUNITY_PROPERTY as COMMUNITY_PROPERTY
    from ..constants import EMBEDDING_DIMENSION as EMBEDDING_DIMENSION
    from ..constants import SIMILARITY_CUTOFF as SIMILARITY_CUTOFF
    from ..constants import SIMILARITY_TOP_K as SIMILARITY_TOP_K

try:
    # Try absolute import when called from CLI wrapper
    from utils.neo4j_utils import ensure_port, get_neo4j_config
except ImportError:
    # Fallback to relative import when used as module
    from ..utils.neo4j_utils import ensure_port, get_neo4j_config

# Connection settings
NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

EMBEDDING_DIM = EMBEDDING_DIMENSION


logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Create SIMILAR relationships between methods and optionally run "
            "Louvain community detection"
        )
    )

    # Import add_common_args - handle both script and module execution
    try:
        from utils.common import add_common_args
    except ImportError:
        from ..utils.common import add_common_args

    add_common_args(parser)  # Adds Neo4j connection and logging args

    # Add similarity-specific arguments
    # Allow environment overrides for defaults while keeping CLI flags authoritative
    env_top_k = os.getenv("SIMILARITY_TOP_K") or os.getenv("SIM_TOP_K")
    env_cutoff = os.getenv("SIMILARITY_CUTOFF") or os.getenv("SIM_CUTOFF")
    try:
        default_top_k = int(env_top_k) if env_top_k is not None else SIMILARITY_TOP_K
    except ValueError:
        default_top_k = SIMILARITY_TOP_K
    try:
        default_cutoff = float(env_cutoff) if env_cutoff is not None else SIMILARITY_CUTOFF
    except ValueError:
        default_cutoff = SIMILARITY_CUTOFF

    parser.add_argument(
        "--top-k",
        type=int,
        default=default_top_k,
        help=f"Number of nearest neighbours (default from env SIMILARITY_TOP_K or SIM_TOP_K, else {SIMILARITY_TOP_K})",
    )
    parser.add_argument(
        "--cutoff",
        type=float,
        default=default_cutoff,
        help=f"Similarity cutoff (default from env SIMILARITY_CUTOFF or SIM_CUTOFF, else {SIMILARITY_CUTOFF})",
    )
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
        default=COMMUNITY_PROPERTY,
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

    # Use consistent logging helper - handle both script and module execution
    try:
        from utils.common import setup_logging
    except ImportError:
        from ..utils.common import setup_logging

    setup_logging(args.log_level, args.log_file)

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
