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

# Embedding metadata
EMBEDDING_TYPE = "graphcodebert-base"
MODEL_NAME = "microsoft/graphcodebert-base"

logger = logging.getLogger(__name__)


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


def get_device():
    """Get the appropriate device for PyTorch computations."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        return torch.device("mps")
    else:
        return torch.device("cpu")


def compute_embeddings(snippets, tokenizer, model, device):
    """Return embeddings for all ``snippets`` in a single forward pass."""
    tokens = tokenizer(
        snippets,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        outputs = model(**tokens)
        vecs = outputs.last_hidden_state[:, 0, :].cpu().numpy()

    embeddings = [v.tolist() for v in vecs]
    logger.debug("Computed %d embeddings", len(embeddings))
    return embeddings


def compute_embedding(code, tokenizer, model, device):
    """Compute embedding for a single code snippet."""
    return compute_embeddings([code], tokenizer, model, device)[0]


def create_directory_structure(session, file_path):
    """Create directory nodes and relationships for the given file path."""
    parts = Path(file_path).parent.parts
    if not parts:
        # File is in root directory
        try:
            session.run("MERGE (:Directory {path:''})")
        except Exception as e:
            logger.error("Neo4j error creating root Directory node: %s", e)
        return

    # Create all directory nodes
    dir_paths = []
    current = []
    for part in parts:
        current.append(part)
        dir_paths.append("/".join(current))

    for dp in dir_paths:
        try:
            session.run("MERGE (:Directory {path:$path})", path=dp)
        except Exception as e:
            logger.error(
                "Neo4j error creating Directory node for %s: %s", dp, e
            )

    # Link root to first directory
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

    # Link adjacent directories
    for parent, child in zip(dir_paths[:-1], dir_paths[1:]):
        try:
            session.run(
                "MERGE (p:Directory {path:$parent}) "
                "MERGE (c:Directory {path:$child}) "
                "MERGE (p)-[:CONTAINS]->(c)",
                parent=parent,
                child=child,
            )
        except Exception as e:
            logger.error(
                "Neo4j error linking directories %s -> %s: %s", parent, child, e
            )


def create_method_calls(session, caller_method, caller_class, caller_file,
                        caller_line, method_node):
    """Create CALLS relationships for method invocations."""
    for _, inv in method_node.filter(javalang.tree.MethodInvocation):
        callee_name = inv.member
        callee_class = None
        if inv.qualifier and inv.qualifier[0].isupper():
            callee_class = inv.qualifier.split(".")[-1]

        cypher = (
            "MATCH (caller:Method {name:$caller_name, file:$caller_file, "
            "line:$caller_line"
        )
        params = {
            "caller_name": caller_method,
            "caller_file": caller_file,
            "caller_line": caller_line,
            "callee_name": callee_name,
        }

        if caller_class is not None:
            cypher += ", class:$caller_class"
            params["caller_class"] = caller_class

        cypher += "}) MERGE (callee:Method {name:$callee_name"

        if callee_class:
            cypher += ", class:$callee_class"
            params["callee_class"] = callee_class

        cypher += "}) MERGE (caller)-[:CALLS]->(callee)"

        try:
            session.run(cypher, params)
        except Exception as e:
            logger.error(
                "Neo4j error creating CALLS relationship %s -> %s in %s: %s",
                caller_method,
                callee_name,
                caller_file,
                e,
            )


def process_java_file(path, tokenizer, model, session, repo_root, device):
    """Parse a Java file, create file and method nodes with embeddings."""
    rel_path = str(path.relative_to(repo_root))

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception as e:
        logger.error("Error reading file %s: %s", rel_path, e)
        return

    # Create directory structure
    create_directory_structure(session, rel_path)

    # Create File node
    try:
        file_embedding = compute_embedding(code, tokenizer, model, device)
        session.run(
            "MERGE (f:File {path: $path}) "
            "SET f.embedding = $embedding, f.embedding_type = $etype",
            path=rel_path,
            embedding=file_embedding,
            etype=EMBEDDING_TYPE,
        )

        # Link file to its parent directory
        parent_dir = (str(Path(rel_path).parent)
                      if Path(rel_path).parent != Path('.') else '')
        session.run(
            "MERGE (d:Directory {path:$dir}) "
            "MERGE (f:File {path:$file}) "
            "MERGE (d)-[:CONTAINS]->(f)",
            dir=parent_dir,
            file=rel_path,
        )
    except Exception as e:
        logger.error("Neo4j error creating File node for %s: %s", rel_path, e)
        return

    # Parse Java code
    try:
        tree = javalang.parse.parse(code)
    except Exception as e:
        logger.warning("Failed to parse Java file %s: %s", rel_path, e)
        return

    # Process methods
    for path_to_node, node in tree.filter(javalang.tree.MethodDeclaration):
        try:
            process_method(
                node, path_to_node, code, rel_path, tokenizer, model, session,
                device
            )
        except Exception as e:
            logger.error(
                "Error processing method %s in %s: %s", node.name, rel_path, e
            )


def process_method(node, path_to_node, code, rel_path, tokenizer, model,
                   session, device):
    """Process a single method declaration."""
    start = node.position.line if node.position else None
    method_name = node.name

    # Find containing class
    class_name = None
    for anc in reversed(path_to_node):
        if isinstance(anc, javalang.tree.ClassDeclaration):
            class_name = anc.name
            break

    # Determine method end line
    end = start
    if node.body and isinstance(node.body, list) and node.body:
        if hasattr(node.body[-1], "position"):
            end = node.body[-1].position.line
    elif node.body and hasattr(node.body, "position"):
        end = node.body.position.line

    # Extract method code
    method_code = ""
    if start and end:
        method_code = "\n".join(code.splitlines()[start - 1: end])

    # Create method embedding
    m_embedding = compute_embedding(method_code, tokenizer, model, device)

    # Create Method node
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

    # Create method call relationships
    create_method_calls(session, method_name, class_name, rel_path, start,
                        node)


def load_repo(repo_url, driver, database=None):
    """Load a Git repository into Neo4j."""
    tmpdir = tempfile.mkdtemp()
    try:
        logger.info("Cloning %s...", repo_url)
        try:
            Repo.clone_from(repo_url, tmpdir)
        except Exception as e:
            logger.error("Error cloning %s: %s", repo_url, e)
            return

        # Initialize model and tokenizer
        logger.info("Loading GraphCodeBERT model...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME)
        device = get_device()
        model = model.to(device)
        logger.info("Using device: %s", device)

        # Process Java files
        repo_root = Path(tmpdir)
        java_files = list(repo_root.rglob("*.java"))
        logger.info("Found %d Java files to process", len(java_files))

        start_total = perf_counter()
        with driver.session(database=database) as session:
            for path in tqdm(java_files, desc="Processing Java files"):
                start = perf_counter()
                process_java_file(
                    path, tokenizer, model, session, repo_root, device
                )
                logger.debug(
                    "Processed %s in %.2fs", path, perf_counter() - start
                )

        logger.info(
            "Processed %d files in %.2fs",
            len(java_files),
            perf_counter() - start_total,
        )
    except Exception as e:
        logger.error("Error while processing repository: %s", e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    args = parse_args()

    # Setup logging
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    # Connect to Neo4j
    try:
        driver = GraphDatabase.driver(
            ensure_port(args.uri), auth=(args.username, args.password)
        )
        driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", ensure_port(args.uri))
    except Exception as e:
        logger.error("Failed to connect to Neo4j: %s", e)
        sys.exit(1)

    try:
        load_repo(args.repo_url, driver, args.database)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
