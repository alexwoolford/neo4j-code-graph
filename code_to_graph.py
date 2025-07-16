import os
import sys
import tempfile
import shutil
from pathlib import Path

from git import Repo
from neo4j import GraphDatabase
from transformers import AutoTokenizer, AutoModel
import torch
import javalang
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse

load_dotenv()


def ensure_port(uri, default=7687):
    """Return URI with default port if none specified."""
    parsed = urlparse(uri)
    # When no netloc is present urlparse puts the host into the path
    host = parsed.hostname or parsed.path
    port = parsed.port
    if port is None:
        # Reconstruct URI with default port and existing auth info
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

# Apply a default port if one is missing from the URI
NEO4J_URI = ensure_port(os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4j")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")


def compute_embedding(code, tokenizer, model):
    tokens = tokenizer(code, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        outputs = model(**tokens)
        vec = outputs.last_hidden_state[:, 0, :].squeeze().cpu().numpy()
    return vec.tolist()


def process_java_file(path, tokenizer, model, session, repo_root):
    """Parse a Java file, create file and method nodes with embeddings."""
    rel_path = str(path.relative_to(repo_root))
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        code = f.read()

    # create File node
    file_embedding = compute_embedding(code, tokenizer, model)
    session.run(
        "MERGE (f:File {path: $path}) SET f.embedding = $embedding",
        path=rel_path,
        embedding=file_embedding,
    )

    try:
        tree = javalang.parse.parse(code)
    except Exception:
        return  # skip unparsable files
    for _, node in tree.filter(javalang.tree.MethodDeclaration):
        start = node.position.line if node.position else None
        method_code = (
            code.splitlines()[node.position.line - 1 : node.body.position.line]
            if node.body
            else ""
        )
        m_embedding = compute_embedding(method_code, tokenizer, model)
        method_name = node.name
        session.run(
            """
            MERGE (m:Method {name:$name, file:$file, line:$line})
            SET m.embedding=$embedding
            MERGE (f:File {path:$file})
            MERGE (f)-[:DECLARES]->(m)
            """,
            name=method_name,
            file=rel_path,
            line=start,
            embedding=m_embedding,
        )


def load_repo(repo_url, driver, database=None):
    tmpdir = tempfile.mkdtemp()
    try:
        print(f"Cloning {repo_url}...")
        Repo.clone_from(repo_url, tmpdir)
        tokenizer = AutoTokenizer.from_pretrained("microsoft/graphcodebert-base")
        model = AutoModel.from_pretrained("microsoft/graphcodebert-base")
        repo_root = Path(tmpdir)
        with driver.session(database=database) as session:
            for path in repo_root.rglob("*.java"):
                process_java_file(path, tokenizer, model, session, repo_root)
    finally:
        shutil.rmtree(tmpdir)


def main():
    if len(sys.argv) != 2:
        print("Usage: python code_to_graph.py <git_repo_url>")
        sys.exit(1)
    repo_url = sys.argv[1]
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    load_repo(repo_url, driver, NEO4J_DATABASE)
    driver.close()


if __name__ == "__main__":
    main()
