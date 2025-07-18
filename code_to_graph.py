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
from utils import ensure_port, get_neo4j_config

# Read connection settings from the environment
NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

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

    for path, node in tree.filter(javalang.tree.MethodDeclaration):
        start = node.position.line if node.position else None

        class_name = None
        for anc in reversed(path):
            if isinstance(anc, javalang.tree.ClassDeclaration):
                class_name = anc.name
                break

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
        try:
            session.run(
                """
                MERGE (m:Method {name:$name, file:$file, line:$line, class:$class})
                SET m.embedding=$embedding, m.embedding_type=$etype
                MERGE (f:File {path:$file})
                MERGE (f)-[:DECLARES]->(m)
                """,
                {
                    "name": method_name,
                    "file": rel_path,
                    "line": start,
                    "class": class_name,
                    "embedding": m_embedding,
                    "etype": EMBEDDING_TYPE,
                },
            )
        except Exception as e:
            print(
                "Neo4j error creating Method node "
                f"{method_name} in {rel_path}: {e}"
            )

        for _, inv in node.filter(javalang.tree.MethodInvocation):
            callee_name = inv.member
            callee_class = None
            if inv.qualifier and inv.qualifier[0].isupper():
                callee_class = inv.qualifier.split(".")[-1]
            cypher = (
                "MATCH (caller:Method {name:$caller_name, file:$caller_file, line:$caller_line, class:$caller_class}) "
                "MERGE (callee:Method {name:$callee_name"
            )
            params = {
                "caller_name": method_name,
                "caller_file": rel_path,
                "caller_line": start,
                "caller_class": class_name,
                "callee_name": callee_name,
            }
            if callee_class:
                cypher += ", class:$callee_class"
                params["callee_class"] = callee_class
            cypher += "}) MERGE (caller)-[:CALLS]->(callee)"
            try:
                session.run(cypher, params)
            except Exception as e:
                print(
                    "Neo4j error creating CALLS relationship "
                    f"{method_name} -> {callee_name} in {rel_path}: {e}"
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
    args = parse_args()
    try:
        driver = GraphDatabase.driver(
            ensure_port(args.uri), auth=(args.username, args.password)
        )
        # Fail fast if the Neo4j connection details are incorrect
        driver.verify_connectivity()
    except Exception as e:
        print(f"Failed to connect to Neo4j: {e}")
        sys.exit(1)

    try:
        load_repo(args.repo_url, driver, args.database)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
