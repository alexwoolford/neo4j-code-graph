import os
from dotenv import load_dotenv
from graphdatascience import GraphDataScience
import argparse

from utils import ensure_port

# Load env vars
load_dotenv(override=True)


NEO4J_URI = ensure_port(os.getenv("NEO4J_URI", "bolt://localhost:7687"))
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

EMBEDDING_DIM = 768


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
    parser.add_argument(
        "--cutoff", type=float, default=0.8, help="Similarity cutoff"
    )
    return parser.parse_args()


def create_index(gds):
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
        "nodeProjection": "Method",
        "nodeProperties": "embedding",
        "topK": top_k,
        "similarityCutoff": cutoff,
        "writeRelationshipType": "SIMILAR",
        "writeProperty": "score",
    }

    try:
        gds.knn.write(**base_config)
    except Exception as e:
        # Older GDS versions expect a graph name as the first argument,
        # which results in a TypeError complaining about a missing "G"
        # parameter.
        if (
            "Type mismatch" not in str(e)
            and "missing 1 required positional argument" not in str(e)
        ):
            raise

        # Drop any existing graph with the same name
        try:
            gds.graph.drop("methodGraph")
        except Exception:
            pass  # Graph doesn't exist, which is fine

        # Create graph projection with node properties included
        graph, _ = gds.graph.project(
            "methodGraph",
            {"Method": {"properties": "embedding"}},
            "*",
        )
        config = {
            k: base_config[k]
            for k in base_config
            if k != "nodeProjection"
        }
        gds.knn.write(graph, **config)
        graph.drop()


def main():
    args = parse_args()

    gds = GraphDataScience(
        ensure_port(args.uri),
        auth=(args.username, args.password),
        database=args.database,
        arrow=False,
    )
    gds.run_cypher("RETURN 1")  # verify connectivity
    create_index(gds)
    run_knn(gds, args.top_k, args.cutoff)
    gds.close()


if __name__ == '__main__':
    main()
