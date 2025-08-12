"""
Resume processing utilities and CLI.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

# Module-scope type aliases for Pyright
Embedding = list[float]
from collections.abc import Callable as _Callable
from collections.abc import Sequence as _Sequence

ComputeFn = _Callable[[_Sequence[str], Any, Any, Any, int], list[Embedding]]
ExtractFileDataFn = _Callable[[Path, Path], dict[str, Any] | None]
ExtractDepsFn = _Callable[[Path], dict[str, str]]

from ..analysis.code_analysis import (
    compute_embeddings_bulk,
    extract_dependency_versions_from_files,
    extract_file_data,
    load_model_and_tokenizer,
)

try:
    from ..analysis.types import FileData
except Exception:
    FileData = dict  # type: ignore[misc,assignment]
from ..utils.common import create_neo4j_driver, get_neo4j_config, setup_logging

logger = logging.getLogger(__name__)


def get_files_needing_embeddings(session: Any, repo_root: Path) -> list[Path]:
    """Find files that exist but don't have embeddings yet."""
    result = session.run(
        """
        MATCH (f:File)
        WHERE f.embedding IS NOT NULL
        RETURN f.path as path
    """
    )
    processed_files = {record["path"] for record in result}

    java_files = list(repo_root.rglob("*.java"))
    files_needing_processing: list[Path] = []
    for java_file in java_files:
        rel_path = str(java_file.relative_to(repo_root))
        if rel_path not in processed_files:
            files_needing_processing.append(java_file)

    logger.info(
        "Found %d files needing embeddings out of %d total",
        len(files_needing_processing),
        len(java_files),
    )
    return files_needing_processing


def process_remaining_files(
    session: Any, files_to_process: list[Path], repo_root: Path, dependency_versions: dict[str, str]
) -> None:
    """Process the remaining files that need embeddings."""
    if not files_to_process:
        logger.info("No files need processing - all files have embeddings")
        return

    logger.info("Processing %d remaining files...", len(files_to_process))

    # Load model for embeddings
    tokenizer, model, device, batch_size = load_model_and_tokenizer()

    # Extract data from remaining files
    files_data: list[FileData] = []
    for java_file in files_to_process:
        logger.info("Extracting data from %s", java_file)
        extract_file: ExtractFileDataFn = extract_file_data
        file_data = extract_file(java_file, repo_root)
        if file_data:
            files_data.append(file_data)

    if not files_data:
        logger.info("No valid file data extracted")
        return

    # Prepare embeddings
    file_snippets: list[str] = [file_data["code"] for file_data in files_data]
    method_snippets: list[str] = []
    for file_data in files_data:
        for method in file_data["methods"]:
            method_snippets.append(method["code"])

    logger.info(
        "Computing embeddings for %d files and %d methods...",
        len(file_snippets),
        len(method_snippets),
    )

    compute_embeddings: ComputeFn = compute_embeddings_bulk
    file_embeddings: list[Embedding] = compute_embeddings(
        file_snippets, tokenizer, model, device, batch_size
    )
    method_embeddings: list[Embedding] = compute_embeddings(
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
            total_lines=int(file_data["total_lines"]),
            code_lines=int(file_data["code_lines"]),
            method_count=int(file_data["method_count"]),
            class_count=int(file_data["class_count"]),
            interface_count=int(file_data["interface_count"]),
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

    logger.info("✅ Completed processing %d files with embeddings", len(files_data))


def main() -> None:
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

    setup_logging(args.log_level)

    repo_root = Path(args.repo_path)
    if not repo_root.exists() or not repo_root.is_dir():
        logger.error("Repository path does not exist: %s", args.repo_path)
        raise SystemExit(1)

    # Get config
    if args.uri:
        config = (args.uri, args.username, args.password, args.database)
    else:
        config = get_neo4j_config()

    with create_neo4j_driver(config[0], config[1], config[2]) as driver:
        with driver.session(database=config[3]) as session:  # type: ignore[reportUnknownMemberType]
            logger.info("🔄 Resuming code processing...")

            # Current state
            stats = session.run(
                "MATCH (f:File) RETURN count(f) as total, count(f.embedding) as with_embeddings"
            ).single()
            if stats:
                logger.info(
                    "Current state: %s/%s files have embeddings",
                    stats["with_embeddings"],
                    stats["total"],
                )

            # Files needing processing
            files_to_process = get_files_needing_embeddings(session, repo_root)
            if files_to_process:
                extract_deps: ExtractDepsFn = extract_dependency_versions_from_files
                dependency_versions: dict[str, str] = extract_deps(repo_root)
                process_remaining_files(session, files_to_process, repo_root, dependency_versions)

            if not args.files_only:
                # Check method calls status
                calls = session.run(
                    "MATCH ()-[r:CALLS]->() RETURN count(r) as calls_count"
                ).single()
                calls_count = int(calls["calls_count"]) if calls and "calls_count" in calls else 0
                logger.info("Current method calls: %s", f"{calls_count:,}")
                if calls_count == 0:
                    logger.info("⚠️  No method calls found - may need re-run")

            logger.info("🎉 Resume processing completed!")


if __name__ == "__main__":
    main()
