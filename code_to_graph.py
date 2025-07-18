import os
import sys
import tempfile
import shutil
from pathlib import Path
import argparse

from git import Repo
from neo4j import GraphDatabase
from transformers import AutoTokenizer, AutoModel
import torch
import javalang
from dotenv import load_dotenv
from utils import ensure_port

# Load environment variables from a .env file and override any existing
# variables so that local configuration takes precedence.
load_dotenv(override=True)

# Apply a default port if one is missing from the URI
NEO4J_URI = ensure_port(os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4j")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Load a Java Git repository into Neo4j with embeddings"
    )
    parser.add_argument("repo_url", help="URL of the Git repository to load")
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
    return parser.parse_args()

# Embedding metadata
EMBEDDING_DIM = 768
EMBEDDING_TYPE = "graphcodebert-base"
MODEL_NAME = "microsoft/graphcodebert-base"


def compute_embedding(code, tokenizer, model):
    tokens = tokenizer(
        code,
        return_tensors="pt",
        truncation=True,
        max_length=512,
    )
    with torch.no_grad():
        outputs = model(**tokens)
        vec = outputs.last_hidden_state[:, 0, :].squeeze().cpu().numpy()
    return vec.tolist()


def process_java_file(path, tokenizer, model, session, repo_root):
    """Parse a Java file, create file and method nodes with embeddings."""
    rel_path = str(path.relative_to(repo_root))
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        code = f.read()

    # Create Directory nodes for each level of the file path
    parts = Path(rel_path).parent.parts
    dir_paths = []
    current = []
    for part in parts:
        current.append(part)
        dir_paths.append("/".join(current))

    for dp in dir_paths:
        try:
            session.run("MERGE (:Directory {path:$path})", path=dp)
        except Exception as e:
            print(f"Neo4j error creating Directory node for {dp}: {e}")

    if not dir_paths:
        try:
            session.run("MERGE (:Directory {path:''})")
        except Exception as e:
            print(f"Neo4j error creating Directory node for root: {e}")
    else:
        try:
            session.run(
                "MERGE (p:Directory {path:''}) "
                "MERGE (c:Directory {path:$child}) "
                "MERGE (p)-[:CONTAINS]->(c)",
                child=dir_paths[0],
            )
        except Exception as e:
            print(f"Neo4j error linking root directory to {dir_paths[0]}: {e}")

    for p, c in zip(dir_paths[:-1], dir_paths[1:]):
        try:
            session.run(
                "MERGE (p:Directory {path:$parent}) "
                "MERGE (c:Directory {path:$child}) "
                "MERGE (p)-[:CONTAINS]->(c)",
                parent=p,
                child=c,
            )
        except Exception as e:
            print(f"Neo4j error linking directories {p} -> {c}: {e}")

    # create File node
    file_embedding = compute_embedding(code, tokenizer, model)
    try:
        session.run(
            "MERGE (f:File {path: $path}) "
            "SET f.embedding = $embedding, "
            "f.embedding_type = $etype",
            path=rel_path,
            embedding=file_embedding,
            etype=EMBEDDING_TYPE,
        )
        if dir_paths:
            session.run(
                "MERGE (d:Directory {path:$dir}) "
                "MERGE (f:File {path:$file}) "
                "MERGE (d)-[:CONTAINS]->(f)",
                dir=dir_paths[-1],
                file=rel_path,
            )
    except Exception as e:
        print(f"Neo4j error creating File node for {rel_path}: {e}")
        return

    try:
        tree = javalang.parse.parse(code)
    except Exception as e:
        print(f"Failed to parse {rel_path}: {e}")
        return  # skip unparsable files

    # -------------------------------------------------------------------
    # Classes and interfaces
    # -------------------------------------------------------------------
    for _, cls in tree.filter(javalang.tree.ClassDeclaration):
        try:
            session.run(
                """
                MERGE (c:Class {name:$name, file:$file})
                MERGE (f:File {path:$file})
                MERGE (f)-[:DECLARES]->(c)
                """,
                name=cls.name,
                file=rel_path,
            )

            if cls.extends:
                session.run(
                    """
                    MERGE (child:Class {name:$name, file:$file})
                    MERGE (parent:Class {name:$parent})
                    MERGE (child)-[:EXTENDS]->(parent)
                    """,
                    name=cls.name,
                    file=rel_path,
                    parent=cls.extends.name,
                )

            for impl in cls.implements or []:
                session.run(
                    """
                    MERGE (child:Class {name:$name, file:$file})
                    MERGE (iface:Interface {name:$iface})
                    MERGE (child)-[:IMPLEMENTS]->(iface)
                    """,
                    name=cls.name,
                    file=rel_path,
                    iface=impl.name,
                )
        except Exception as e:
            print(f"Neo4j error creating Class node for {cls.name} in {rel_path}: {e}")

    for path_nodes, node in tree.filter(javalang.tree.MethodDeclaration):
        start = node.position.line if node.position else None

        end = start
        if node.body:
            if isinstance(node.body, list):
                # For normal methods javalang returns a list of statements
                # each with its own position.
                if node.body and hasattr(node.body[-1], "position"):
                    end = node.body[-1].position.line
            elif hasattr(node.body, "position"):
                # Some nodes expose a body object with a position attribute
                end = node.body.position.line

        method_code = (
            "\n".join(code.splitlines()[start - 1 : end])
            if start and end
            else ""
        )
        m_embedding = compute_embedding(method_code, tokenizer, model)
        method_name = node.name

        # Find the nearest enclosing class for this method
        cls_name = None
        for ancestor in reversed(path_nodes):
            if isinstance(ancestor, javalang.tree.ClassDeclaration):
                cls_name = ancestor.name
                break
        try:
            session.run(
                """
                MERGE (m:Method {name:$name, file:$file, line:$line})
                SET m.embedding=$embedding, m.embedding_type=$etype
                MERGE (f:File {path:$file})
                MERGE (f)-[:DECLARES]->(m)
                """,
                name=method_name,
                file=rel_path,
                line=start,
                embedding=m_embedding,
                etype=EMBEDDING_TYPE,
            )

            if cls_name:
                session.run(
                    """
                    MATCH (c:Class {name:$cname, file:$file})
                    MATCH (m:Method {name:$name, file:$file, line:$line})
                    MERGE (c)-[:DECLARES]->(m)
                    """,
                    cname=cls_name,
                    file=rel_path,
                    name=method_name,
                    line=start,
                )

            for _, inv in node.filter(javalang.tree.MethodInvocation):
                callee = inv.member
                session.run(
                    """
                    MATCH (caller:Method {name:$caller, file:$file, line:$line})
                    MATCH (callee:Method {name:$callee})
                    MERGE (caller)-[:CALLS]->(callee)
                    """,
                    caller=method_name,
                    callee=callee,
                    file=rel_path,
                    line=start,
                )
        except Exception as e:
            print(
                "Neo4j error creating Method node "
                f"{method_name} in {rel_path}: {e}"
            )


def load_repo(repo_url, driver, database=None):
    tmpdir = tempfile.mkdtemp()
    try:
        print(f"Cloning {repo_url}...")
        try:
            Repo.clone_from(repo_url, tmpdir)
        except Exception as e:
            print(f"Error cloning {repo_url}: {e}")
            return
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME)
        repo_root = Path(tmpdir)
        try:
            with driver.session(database=database) as session:
                for path in repo_root.rglob("*.java"):
                    process_java_file(
                        path,
                        tokenizer,
                        model,
                        session,
                        repo_root,
                    )
        except Exception as e:
            print(f"Neo4j error while processing repository: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        print("Usage: python code_to_graph.py <git_repo_url>")
        sys.exit(1)
    repo_url = sys.argv[1]
    try:
        driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
        )
        # Fail fast if the Neo4j connection details are incorrect
        driver.verify_connectivity()
    except Exception as e:
        print(f"Failed to connect to Neo4j: {e}")
        sys.exit(1)

    try:
        load_repo(repo_url, driver, NEO4J_DATABASE)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
