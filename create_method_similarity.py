import os
from urllib.parse import urlparse, urlunparse
from dotenv import load_dotenv
from neo4j import GraphDatabase

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


def create_index(session):
    session.run(
        """
        CREATE VECTOR INDEX method_embeddings IF NOT EXISTS
        FOR (m:Method) ON (m.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: $dim,
            `vector.similarity_function`: 'cosine'
        }}
        """,
        dim=EMBEDDING_DIM,
    )
    session.run("CALL db.index.awaitIndex('method_embeddings')")


def run_knn(session, top_k=5, cutoff=0.8):
    session.run(
        """
        CALL gds.knn.write({
            nodeProjection: 'Method',
            nodeProperties: 'embedding',
            topK: $top_k,
            similarityCutoff: $cutoff,
            writeRelationshipType: 'SIMILAR',
            writeProperty: 'score'
        })
        """,
        top_k=top_k,
        cutoff=cutoff,
    )


def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    driver.verify_connectivity()
    with driver.session(database=NEO4J_DATABASE) as session:
        create_index(session)
        run_knn(session)
    driver.close()


if __name__ == '__main__':
    main()
