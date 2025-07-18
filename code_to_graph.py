import sys
import tempfile
import shutil
from pathlib import Path
import argparse
import logging
from time import perf_counter
from tqdm import tqdm

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


# Embedding metadata
EMBEDDING_TYPE = "graphcodebert-base"
MODEL_NAME = "microsoft/graphcodebert-base"


logger = logging.getLogger(__name__)


def compute_embeddings(snippets, tokenizer, model, device=None):
    """Return embeddings for all ``snippets`` in a single forward pass."""
    if device is None:
        device = model.device
    tokens = tokenizer(
        snippets,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(device)
    model = model.to(device)
    with torch.no_grad():
        outputs = model(**tokens)
        vecs = outputs.last_hidden_state[:, 0, :].cpu().numpy()
    embeddings = [v.tolist() for v in vecs]
    logger.debug("Computed %d embeddings", len(embeddings))
    return embeddings


def compute_embedding(code, tokenizer, model, device=None):
    return compute_embeddings([code], tokenizer, model, device=device)[0]


def process_java_file(path, tokenizer, model, session, repo_root, device=None):
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
            logger.error("Neo4j error creating Directory node for %s: %s", dp, e)

    if not dir_paths:
        try:
            session.run("MERGE (:Directory {path:''})")
        except Exception as e:
            logger.error("Neo4j error creating Directory node for root: %s", e)
    else:
        try:
            session.run(
                "MERGE (p:Directory {path:''}) "
                "MERGE (c:Directory {path:$child}) "
                "MERGE (p)-[:CONTAINS]->(c)",
                child=dir_paths[0],
            )
        except Exception as e:
            logger.error(
                "Neo4j error linking root directory to %s: %s", dir_paths[0], e
            )

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
            logger.error("Neo4j error linking directories %s -> %s: %s", p, c, e)

    # create File node
    file_embedding = compute_embedding(code, tokenizer, model, device=device)
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
        logger.error("Neo4j error creating File node for %s: %s", rel_path, e)
        return

    try:
        tree = javalang.parse.parse(code)
    except Exception as e:
        logger.warning("Failed to parse %s: %s", rel_path, e)
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
            "\n".join(code.splitlines()[start - 1 : end]) if start and end else ""
        )
        m_embedding = compute_embedding(method_code, tokenizer, model, device=device)
        method_name = node.name
        try:
            cypher = "MERGE (m:Method {name:$name, file:$file, line:$line"
            params = {
                "name": method_name,
                "file": rel_path,
                "line": start,
                "embedding": m_embedding,
                "etype": EMBEDDING_TYPE,
            }
            if class_name is not None:
                cypher += ", class:$class"
                params["class"] = class_name
            cypher += "}) SET m.embedding=$embedding, m.embedding_type=$etype "
            cypher += "MERGE (f:File {path:$file}) MERGE (f)-[:DECLARES]->(m)"
            session.run(cypher, params)
        except Exception as e:
            print(
                "Neo4j error creating Method node " f"{method_name} in {rel_path}: {e}"
            )

        for _, inv in node.filter(javalang.tree.MethodInvocation):
            callee_name = inv.member
            callee_class = None
            if inv.qualifier and inv.qualifier[0].isupper():
                callee_class = inv.qualifier.split(".")[-1]
            cypher = (
                "MATCH (caller:Method {name:$caller_name, file:$caller_file,"
                " line:$caller_line"
            )
            params = {
                "caller_name": method_name,
                "caller_file": rel_path,
                "caller_line": start,
                "callee_name": callee_name,
            }
            if class_name is not None:
                cypher += ", class:$caller_class"
                params["caller_class"] = class_name
            cypher += "}) MERGE (callee:Method {name:$callee_name"
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
        logger.info("Cloning %s...", repo_url)
        try:
            Repo.clone_from(repo_url, tmpdir)
        except Exception as e:
            logger.error("Error cloning %s: %s", repo_url, e)
            return
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME)
        if hasattr(torch, "device"):
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            device = "cpu"
        if hasattr(model, "to"):
            model = model.to(device)
        repo_root = Path(tmpdir)
        try:
            java_files = list(repo_root.rglob("*.java"))
            start_total = perf_counter()
            with driver.session(database=database) as session:
                for path in tqdm(java_files, desc="Processing Java files"):
                    start = perf_counter()
                    process_java_file(
                        path,
                        tokenizer,
                        model,
                        session,
                        repo_root,
                        device,
                    )
                    logger.debug("Processed %s in %.2fs", path, perf_counter() - start)
            logger.info(
                "Processed %d files in %.2fs",
                len(java_files),
                perf_counter() - start_total,
            )
        except Exception as e:
            logger.error("Neo4j error while processing repository: %s", e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
    try:
        driver = GraphDatabase.driver(
            ensure_port(args.uri), auth=(args.username, args.password)
        )
        # Fail fast if the Neo4j connection details are incorrect
        driver.verify_connectivity()
    except Exception as e:
        logger.error("Failed to connect to Neo4j: %s", e)
        sys.exit(1)

    try:
        load_repo(args.repo_url, driver, args.database)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
