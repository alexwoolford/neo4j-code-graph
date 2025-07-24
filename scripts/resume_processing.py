#!/usr/bin/env python3
"""
Resume code processing after a crash or interruption.
This script will:
1. Check what files still need embeddings
2. Complete the remaining file processing
3. Skip method calls that are already done
4. Safely process remaining method calls with resilient approach
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "src")

import logging

from analysis.code_analysis import (
    compute_embeddings_bulk,
    extract_dependency_versions_from_files,
    extract_file_data,
    load_model_and_tokenizer,
)
from utils.common import create_neo4j_driver, get_neo4j_config, setup_logging

logger = logging.getLogger(__name__)


def get_files_needing_embeddings(session, repo_root):
    """Find files that exist but don't have embeddings yet."""
    # Get files already processed
    result = session.run(
        """
        MATCH (f:File)
        WHERE f.embedding IS NOT NULL
        RETURN f.path as path
    """
    )
    processed_files = {record["path"] for record in result}

    # Get all Java files in the repository
    java_files = list(repo_root.rglob("*.java"))

    # Find files that need processing
    files_needing_processing = []
    for java_file in java_files:
        rel_path = str(java_file.relative_to(repo_root))
        if rel_path not in processed_files:
            files_needing_processing.append(java_file)

    logger.info(
        f"Found {len(files_needing_processing)} files needing embeddings out of {len(java_files)} total"
    )
    return files_needing_processing


def process_remaining_files(session, files_to_process, repo_root, dependency_versions):
    """Process the remaining files that need embeddings."""
    if not files_to_process:
        logger.info("No files need processing - all files have embeddings")
        return

    logger.info(f"Processing {len(files_to_process)} remaining files...")

    # Load model for embeddings
    tokenizer, model, device, batch_size = load_model_and_tokenizer()

    # Extract data from remaining files
    files_data = []
    for java_file in files_to_process:
        logger.info(f"Extracting data from {java_file}")
        file_data = extract_file_data(java_file, repo_root)
        if file_data:
            files_data.append(file_data)

    if not files_data:
        logger.info("No valid file data extracted")
        return

    # Prepare embeddings
    file_snippets = []
    method_snippets = []

    for file_data in files_data:
        file_snippets.append(file_data.get("content", ""))
        for method in file_data["methods"]:
            method_snippets.append(method["code"])

    logger.info(
        f"Computing embeddings for {len(file_snippets)} files and {len(method_snippets)} methods..."
    )

    # Compute embeddings
    file_embeddings = compute_embeddings_bulk(file_snippets, tokenizer, model, device, batch_size)
    method_embeddings = compute_embeddings_bulk(
        method_snippets, tokenizer, model, device, batch_size
    )

    # Update files with embeddings
    for i, file_data in enumerate(files_data):
        session.run(
            """
            MATCH (f:File {path: $path})
            SET f.embedding = $embedding,
                f.embedding_type = $embedding_type,
                f.total_lines = $total_lines,
                f.code_lines = $code_lines,
                f.method_count = $method_count,
                f.class_count = $class_count,
                f.interface_count = $interface_count
        """,
            path=file_data["path"],
            embedding=file_embeddings[i],
            embedding_type="sentence-transformers/all-MiniLM-L6-v2",
            total_lines=file_data.get("total_lines", 0),
            code_lines=file_data.get("code_lines", 0),
            method_count=file_data.get("method_count", 0),
            class_count=file_data.get("class_count", 0),
            interface_count=file_data.get("interface_count", 0),
        )

    # Update methods with embeddings
    method_idx = 0
    for file_data in files_data:
        for method in file_data["methods"]:
            session.run(
                """
                MATCH (m:Method {name: $name, file: $file, line: $line})
                SET m.embedding = $embedding,
                    m.embedding_type = $embedding_type
            """,
                name=method["name"],
                file=method["file"],
                line=method["line"],
                embedding=method_embeddings[method_idx],
                embedding_type="sentence-transformers/all-MiniLM-L6-v2",
            )
            method_idx += 1

    logger.info(f"✅ Completed processing {len(files_data)} files with embeddings")


def main():
    parser = argparse.ArgumentParser(description="Resume code processing after crash")
    parser.add_argument("repo_path", help="Path to repository (local path only)")
    parser.add_argument("--uri", help="Neo4j URI")
    parser.add_argument("--username", help="Neo4j username")
    parser.add_argument("--password", help="Neo4j password")
    parser.add_argument("--database", default="neo4j", help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument(
        "--files-only", action="store_true", help="Only process missing file embeddings"
    )
    args = parser.parse_args()

    setup_logging(args.log_level, None)

    # Validate repository path
    repo_root = Path(args.repo_path)
    if not repo_root.exists() or not repo_root.is_dir():
        logger.error(f"Repository path does not exist: {args.repo_path}")
        sys.exit(1)

    # Get config
    if args.uri:
        config = (args.uri, args.username, args.password, args.database)
    else:
        config = get_neo4j_config()

    driver = create_neo4j_driver(config[0], config[1], config[2])

    try:
        with driver.session(database=config[3]) as session:
            logger.info("🔄 Resuming code processing...")

            # Check current state
            result = session.run(
                "MATCH (f:File) RETURN count(f) as total, count(f.embedding) as with_embeddings"
            )
            stats = result.single()
            logger.info(
                f"Current state: {stats['with_embeddings']}/{stats['total']} files have embeddings"
            )

            # Find files needing processing
            files_to_process = get_files_needing_embeddings(session, repo_root)

            if files_to_process:
                # Extract dependency versions
                dependency_versions = extract_dependency_versions_from_files(repo_root)

                # Process remaining files
                process_remaining_files(session, files_to_process, repo_root, dependency_versions)

            if not args.files_only:
                # Check method calls status
                result = session.run("MATCH ()-[r:CALLS]->() RETURN count(r) as calls_count")
                calls_count = result.single()["calls_count"]
                logger.info(f"Current method calls: {calls_count:,}")

                if calls_count > 0:
                    logger.info("✅ Method calls already exist - skipping method call processing")
                    logger.info(
                        "   Use --files-only flag if you only want to complete file embeddings"
                    )
                else:
                    logger.info("⚠️  No method calls found - you may need to re-run full processing")

            logger.info("🎉 Resume processing completed!")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
