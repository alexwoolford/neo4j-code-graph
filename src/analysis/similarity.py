import argparse
import logging
import os
from time import perf_counter
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:  # don't import heavy deps at module import time
    from graphdatascience import GraphDataScience
else:
    GraphDataScience = Any  # type: ignore

try:
    # When 'src' is on sys.path and importing as top-level package
    from constants import (
        COMMUNITY_PROPERTY,
        EMBEDDING_DIMENSION,
        EMBEDDING_PROPERTY,
        EMBEDDING_TYPE,
        SIMILARITY_CUTOFF,
        SIMILARITY_TOP_K,
    )
except Exception:
    try:
        # Package name import
        from src.constants import (
            COMMUNITY_PROPERTY,
            EMBEDDING_DIMENSION,
            EMBEDDING_PROPERTY,
            EMBEDDING_TYPE,
            SIMILARITY_CUTOFF,
            SIMILARITY_TOP_K,
        )
    except Exception:
        # Relative import when used as module inside package
        from ..constants import COMMUNITY_PROPERTY as COMMUNITY_PROPERTY
        from ..constants import EMBEDDING_DIMENSION as EMBEDDING_DIMENSION
        from ..constants import EMBEDDING_PROPERTY as EMBEDDING_PROPERTY
        from ..constants import EMBEDDING_TYPE as EMBEDDING_TYPE
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


def parse_args() -> argparse.Namespace:
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


def create_index(gds: GraphDataScience) -> None:
    logger.info("Ensuring vector index exists")
    index_name = f"method_embeddings_{EMBEDDING_PROPERTY}"
    gds.run_cypher(
        f"""
        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
        FOR (m:Method) ON (m.{EMBEDDING_PROPERTY})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: $dim,
            `vector.similarity_function`: 'cosine'
        }}}}
        """,
        params={"dim": EMBEDDING_DIM},
    )
    # Neo4j 5.x: prefer awaiting all indexes (specific awaitIndex may not be present)
    gds.run_cypher("CALL db.awaitIndexes()")


def _extract_count(df: Any, preferred_column: str) -> int:
    """Return an integer count from a pandas DataFrame or other truthy return.

    - Prefer a specific column if present
    - Otherwise fall back to the first cell
    - If df is falsy or empty, return 0
    """
    try:
        import pandas as pd  # type: ignore

        if df is None:
            return 0
        if isinstance(df, pd.DataFrame):
            if df.empty:
                return 0
            if preferred_column in df.columns:
                return int(df.iloc[0][preferred_column])
            # Fallback: take the first column's first row
            return int(df.iloc[0][df.columns[0]])
    except Exception:
        pass
    try:
        return int(df)
    except Exception:
        return 0


def run_knn(gds: GraphDataScience, top_k: int = 5, cutoff: float = 0.8) -> None:
    """Run the KNN algorithm and create SIMILAR relationships."""
    base_config = {
        # Use the property name in the projected in-memory graph (alias below)
        "nodeProperties": "embedding",
        "topK": top_k,
        "similarityCutoff": cutoff,
        "writeRelationshipType": "SIMILAR",
        "writeProperty": "score",
    }

    missing_df = gds.run_cypher(
        f"MATCH (m:Method) WHERE m.{EMBEDDING_PROPERTY} IS NULL RETURN count(m) AS missing"
    )
    missing = _extract_count(missing_df, "missing")

    if missing:
        logger.warning("Ignoring %d Method nodes without embeddings", missing)

    # Strict precondition: ensure there are methods with the configured embedding property
    with_emb_df = gds.run_cypher(
        f"MATCH (m:Method) WHERE m.{EMBEDDING_PROPERTY} IS NOT NULL RETURN count(m) AS withEmb"
    )
    with_emb = _extract_count(with_emb_df, "withEmb")
    if with_emb == 0:
        raise RuntimeError(
            "No Method nodes have the configured embedding property set. "
            f"Expected property: '{EMBEDDING_PROPERTY}'. Ensure the embedding stage ran and wrote "
            "method embeddings, and that the embedding property name is consistent across the pipeline."
        )

    # Proceed even if there are no embedding vectors; upstream steps should have created them.

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
            f"MATCH (m:Method) WHERE m.{EMBEDDING_PROPERTY} IS NOT NULL "
            f"RETURN id(m) AS id, m.{EMBEDDING_PROPERTY} AS embedding"
        ),
        "RETURN null AS source, null AS target LIMIT 0",
    )

    start = perf_counter()
    gds.knn.write(graph, **base_config)
    # Persist provenance of the embedding model on the relationships
    gds.run_cypher("MATCH ()-[s:SIMILAR]->() SET s.model = $m", params={"m": EMBEDDING_TYPE})
    logger.info(
        "kNN wrote relationships for top %d with cutoff %.2f in %.2fs",
        top_k,
        cutoff,
        perf_counter() - start,
    )
    graph.drop()


def run_louvain(
    gds: GraphDataScience, threshold: float = 0.8, community_property: str = "similarityCommunity"
) -> None:
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


def main() -> None:
    args = parse_args()

    # Use consistent logging helper - handle both script and module execution
    try:
        from utils.common import setup_logging
    except ImportError:
        from ..utils.common import setup_logging

    setup_logging(args.log_level, args.log_file)

    from graphdatascience import GraphDataScience as _GDS  # local import

    gds = _GDS(
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
