#!/usr/bin/env python3

import argparse
import logging
import tempfile
from pathlib import Path
from time import perf_counter
import gc
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

import torch
import javalang
from neo4j import GraphDatabase
from transformers import AutoModel, AutoTokenizer
from tqdm import tqdm

from common import setup_logging, create_neo4j_driver, add_common_args

logger = logging.getLogger(__name__)

MODEL_NAME = "microsoft/graphcodebert-base"
EMBEDDING_TYPE = "graphcodebert"


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Ultra-optimized Java code structure and embeddings loader"
    )
    add_common_args(parser)
    parser.add_argument("repo_url", help="Git repository URL to analyze")
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Override automatic batch size selection"
    )
    parser.add_argument(
        "--parallel-files",
        type=int,
        default=4,
        help="Number of files to process in parallel"
    )
    return parser.parse_args()


def get_device():
    """Get the appropriate device for PyTorch computations."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    else:
        return torch.device("cpu")


def get_optimal_batch_size(device):
    """Determine optimal batch size based on device and available memory."""
    if device.type == "cuda":
        gpu_memory = torch.cuda.get_device_properties(0).total_memory
        if gpu_memory > 20 * 1024**3:  # >20GB (RTX 4090, etc.)
            return 512  # Push even harder
        elif gpu_memory > 10 * 1024**3:  # >10GB 
            return 256
        else:  # 8GB or less
            return 128
    elif device.type == "mps":
        return 64
    else:
        return 32


def compute_embeddings_bulk(snippets, tokenizer, model, device, batch_size):
    """Compute embeddings for all snippets using maximum batching."""
    if not snippets:
        return []
    
    logger.info(f"Computing {len(snippets)} embeddings with batch size {batch_size}")
    
    all_embeddings = []
    use_amp = device.type == "cuda" and hasattr(torch.cuda, "amp")
    
    # Process in batches
    for i in tqdm(range(0, len(snippets), batch_size), desc="Computing embeddings"):
        batch_snippets = snippets[i:i + batch_size]
        
        # Tokenize batch
        tokens = tokenizer(
            batch_snippets,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        
        # Move to device efficiently
        tokens = {k: v.to(device, non_blocking=True) for k, v in tokens.items()}

        # Compute embeddings
        with torch.no_grad():
            if use_amp:
                with torch.amp.autocast('cuda'):
                    outputs = model(**tokens)
            else:
                outputs = model(**tokens)
            
            # Use [CLS] token embedding (first token)
            embeddings = outputs.last_hidden_state[:, 0, :].cpu().numpy()
            
        # Convert to lists and store
        batch_embeddings = [embedding.tolist() for embedding in embeddings]
        all_embeddings.extend(batch_embeddings)
        
        # Cleanup
        del tokens, outputs, embeddings
        if i % (batch_size * 4) == 0:  # Periodic cleanup
            gc.collect()
            if device.type == "cuda":
                torch.cuda.empty_cache()
    
    logger.info(f"Computed {len(all_embeddings)} embeddings")
    return all_embeddings


def extract_file_data(file_path, repo_root):
    """Extract all data from a single Java file."""
    rel_path = str(file_path.relative_to(repo_root))
    
    try:
        # Read file
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception as e:
        logger.error("Error reading file %s: %s", file_path, e)
        return None

    # Parse Java and extract methods
    methods = []
    try:
        tree = javalang.parse.parse(code)
        
        # Extract method declarations
        for path_to_node, node in tree.filter(javalang.tree.MethodDeclaration):
            try:
                start_line = node.position.line if node.position else None
                method_name = node.name

                # Find containing class
                class_name = None
                for ancestor in reversed(path_to_node):
                    if isinstance(ancestor, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
                        class_name = ancestor.name
                        break

                # Extract method code (simple approach)
                method_code = ""
                if start_line:
                    code_lines = code.splitlines()
                    end_line = start_line
                    brace_count = 0
                    
                    # Find method end by counting braces
                    for i, line in enumerate(code_lines[start_line - 1:], start_line - 1):
                        if '{' in line:
                            brace_count += line.count('{')
                        if '}' in line:
                            brace_count -= line.count('}')
                            if brace_count <= 0:
                                end_line = i + 1
                                break
                        if i - start_line > 200:  # Safety limit
                            end_line = i + 1
                            break
                    
                    method_code = "\n".join(code_lines[start_line - 1:end_line])

                methods.append({
                    'name': method_name,
                    'class': class_name,
                    'line': start_line,
                    'code': method_code,
                    'file': rel_path
                })

            except Exception as e:
                logger.debug("Error processing method %s in %s: %s", node.name, rel_path, e)
                continue

    except Exception as e:
        logger.warning("Failed to parse Java file %s: %s", rel_path, e)

    return {
        'path': rel_path,
        'code': code,
        'methods': methods
    }


def bulk_create_nodes_and_relationships(session, files_data, file_embeddings, method_embeddings):
    """Create all nodes and relationships using bulk operations."""
    logger.info("Creating directory structure...")
    
    # 1. Create all directories first
    directories = set()
    for file_data in files_data:
        path_parts = Path(file_data['path']).parent.parts
        for i in range(len(path_parts) + 1):
            dir_path = str(Path(*path_parts[:i])) if i > 0 else ""
            directories.add(dir_path)
    
    # Bulk create directories
    session.run(
        "UNWIND $directories AS dir_path "
        "MERGE (:Directory {path: dir_path})",
        directories=list(directories)
    )
    
    # 2. Create directory relationships
    dir_relationships = []
    for directory in directories:
        if directory:  # Not root
            parent = str(Path(directory).parent) if Path(directory).parent != Path(".") else ""
            dir_relationships.append({"parent": parent, "child": directory})
    
    if dir_relationships:
        session.run(
            "UNWIND $rels AS rel "
            "MATCH (parent:Directory {path: rel.parent}) "
            "MATCH (child:Directory {path: rel.child}) "
            "MERGE (parent)-[:CONTAINS]->(child)",
            rels=dir_relationships
        )
    
    logger.info("Creating file nodes...")
    
    # 3. Bulk create file nodes
    file_nodes = []
    for i, file_data in enumerate(files_data):
        file_nodes.append({
            "path": file_data['path'],
            "embedding": file_embeddings[i],
            "embedding_type": EMBEDDING_TYPE
        })
    
    session.run(
        "UNWIND $files AS file "
        "MERGE (f:File {path: file.path}) "
        "SET f.embedding = file.embedding, f.embedding_type = file.embedding_type",
        files=file_nodes
    )
    
    # 4. Create file-to-directory relationships
    file_dir_rels = []
    for file_data in files_data:
        parent_dir = str(Path(file_data['path']).parent) if Path(file_data['path']).parent != Path(".") else ""
        file_dir_rels.append({"file": file_data['path'], "directory": parent_dir})
    
    session.run(
        "UNWIND $rels AS rel "
        "MATCH (d:Directory {path: rel.directory}) "
        "MATCH (f:File {path: rel.file}) "
        "MERGE (d)-[:CONTAINS]->(f)",
        rels=file_dir_rels
    )
    
    logger.info("Creating method nodes...")
    
    # 5. Bulk create method nodes
    method_nodes = []
    method_idx = 0
    
    for file_data in files_data:
        for method in file_data['methods']:
            method_node = {
                "name": method['name'],
                "file": method['file'],
                "line": method['line'],
                "embedding": method_embeddings[method_idx],
                "embedding_type": EMBEDDING_TYPE
            }
            if method['class']:
                method_node["class"] = method['class']
            
            method_nodes.append(method_node)
            method_idx += 1
    
    # Split method creation into batches to avoid huge queries
    batch_size = 1000
    for i in range(0, len(method_nodes), batch_size):
        batch = method_nodes[i:i + batch_size]
        session.run(
            "UNWIND $methods AS method "
            "MERGE (m:Method {name: method.name, file: method.file, line: method.line}) "
            "SET m.embedding = method.embedding, m.embedding_type = method.embedding_type "
            + ("SET m.class = method.class " if any("class" in m for m in batch) else ""),
            methods=batch
        )
    
    # 6. Create method-to-file relationships
    method_file_rels = []
    for file_data in files_data:
        for method in file_data['methods']:
            method_file_rels.append({
                "method_name": method['name'],
                "method_line": method['line'],
                "file_path": method['file']
            })
    
    # Batch the relationships too
    for i in range(0, len(method_file_rels), batch_size):
        batch = method_file_rels[i:i + batch_size]
        session.run(
            "UNWIND $rels AS rel "
            "MATCH (f:File {path: rel.file_path}) "
            "MATCH (m:Method {name: rel.method_name, file: rel.file_path, line: rel.method_line}) "
            "MERGE (f)-[:DECLARES]->(m)",
            rels=batch
        )
    
    logger.info("Bulk creation completed!")


def main():
    """Main function."""
    args = parse_args()
    
    setup_logging(args.log_level, args.log_file)
    driver = create_neo4j_driver(args.uri, args.username, args.password)
    
    try:
        with driver.session(database=args.database) as session:
            # Clone repository
            with tempfile.TemporaryDirectory() as tmpdir:
                logger.info("Cloning %s...", args.repo_url)
                import git
                git.Repo.clone_from(args.repo_url, tmpdir)
                
                repo_root = Path(tmpdir)
                java_files = list(repo_root.rglob("*.java"))
                logger.info("Found %d Java files to process", len(java_files))
                
                # Phase 1: Extract all file data in parallel
                logger.info("Phase 1: Extracting file data...")
                start_phase1 = perf_counter()
                
                files_data = []
                with ThreadPoolExecutor(max_workers=args.parallel_files) as executor:
                    future_to_file = {
                        executor.submit(extract_file_data, file_path, repo_root): file_path 
                        for file_path in java_files
                    }
                    
                    for future in tqdm(as_completed(future_to_file), total=len(java_files), desc="Extracting files"):
                        result = future.result()
                        if result:
                            files_data.append(result)
                
                phase1_time = perf_counter() - start_phase1
                logger.info("Phase 1 completed in %.2fs", phase1_time)
                
                # Phase 2: Compute all embeddings in bulk
                logger.info("Phase 2: Computing embeddings...")
                start_phase2 = perf_counter()
                
                # Initialize model
                logger.info("Loading GraphCodeBERT model...")
                tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
                model = AutoModel.from_pretrained(MODEL_NAME)
                device = get_device()
                model = model.to(device)
                
                batch_size = args.batch_size if args.batch_size else get_optimal_batch_size(device)
                logger.info("Using device: %s", device)
                logger.info("Using batch size: %d", batch_size)
                
                # Collect all code snippets
                file_snippets = [file_data['code'] for file_data in files_data]
                method_snippets = []
                for file_data in files_data:
                    for method in file_data['methods']:
                        method_snippets.append(method['code'])
                
                logger.info("Computing embeddings for %d files and %d methods", 
                           len(file_snippets), len(method_snippets))
                
                # Compute embeddings
                file_embeddings = compute_embeddings_bulk(file_snippets, tokenizer, model, device, batch_size)
                method_embeddings = compute_embeddings_bulk(method_snippets, tokenizer, model, device, batch_size)
                
                phase2_time = perf_counter() - start_phase2
                logger.info("Phase 2 completed in %.2fs", phase2_time)
                
                # Phase 3: Bulk insert into Neo4j
                logger.info("Phase 3: Bulk database operations...")
                start_phase3 = perf_counter()
                
                bulk_create_nodes_and_relationships(session, files_data, file_embeddings, method_embeddings)
                
                phase3_time = perf_counter() - start_phase3
                logger.info("Phase 3 completed in %.2fs", phase3_time)
                
                total_time = phase1_time + phase2_time + phase3_time
                logger.info("TOTAL: Processed %d files in %.2fs (%.2f files/sec)", 
                           len(files_data), total_time, len(files_data) / total_time)
                logger.info("Phase breakdown: Extract=%.1fs, Embeddings=%.1fs, Database=%.1fs",
                           phase1_time, phase2_time, phase3_time)

    finally:
        driver.close()


if __name__ == "__main__":
    main() 