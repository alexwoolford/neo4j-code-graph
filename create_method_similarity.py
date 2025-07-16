import os
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv
from graphdatascience import GraphDataScience

# Load env vars
load_dotenv(override=True)


def ensure_port(uri, default=7687):
    parsed = urlparse(uri)
    host = parsed.hostname or parsed.path
    port = parsed.port
    if port is None:
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth += f":{parsed.password}"
            auth += "@"
        netloc = f"{auth}{host}:{default}"
        parsed = parsed._replace(netloc=netloc, path="")
        uri = urlunparse(parsed)
    return uri


NEO4J_URI = ensure_port(os.getenv("NEO4J_URI", "bolt://localhost:7687"))
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

EMBEDDING_DIM = 768


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
        # Older GDS versions expect a graph name as the first argument.
        if "Type mismatch" not in str(e):
            raise

        gds.graph.project("methodGraph", "Method", {})
        config = {k: base_config[k] for k in base_config if k != "nodeProjection"}
        gds.knn.write("methodGraph", **config)
        gds.graph.drop("methodGraph")


def main():
    gds = GraphDataScience(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        database=NEO4J_DATABASE,
        arrow=False,
    )
    gds.run_cypher("RETURN 1")  # verify connectivity
    create_index(gds)
    run_knn(gds)
    gds.close()


if __name__ == '__main__':
    main()
