#!/usr/bin/env python3

import argparse

try:
    from src.constants import DEFAULT_PARALLEL_FILES  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from constants import DEFAULT_PARALLEL_FILES  # type: ignore

try:
    from src.utils.common import add_common_args  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from utils.common import add_common_args  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Java code structure and embeddings loader")
    add_common_args(parser)
    parser.add_argument("repo_url", help="Git repository URL or local path to analyze")
    parser.add_argument("--batch-size", type=int, help="Override automatic batch size selection")
    parser.add_argument(
        "--parallel-files",
        type=int,
        default=DEFAULT_PARALLEL_FILES,
        help="Number of files to process in parallel",
    )
    parser.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Force reprocessing of all files even if they exist in database",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database writes (extract + embeddings only) for benchmarking",
    )
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Skip embedding computation (extract only) for benchmarking",
    )
    parser.add_argument(
        "--embed-target",
        choices=["files", "methods", "both"],
        default="both",
        help="Which embeddings to compute (default: both)",
    )
    # Artifact inputs/outputs to enable granular pipeline tasks
    parser.add_argument("--out-files-data", help="Write extracted files data JSON to this path")
    parser.add_argument("--in-files-data", help="Read extracted files data JSON from this path")
    parser.add_argument("--out-file-embeddings", help="Write file embeddings (NPZ) to this path")
    parser.add_argument(
        "--out-method-embeddings", help="Write method embeddings (NPZ) to this path"
    )
    parser.add_argument("--in-file-embeddings", help="Read file embeddings (NPZ) from this path")
    parser.add_argument(
        "--in-method-embeddings", help="Read method embeddings (NPZ) from this path"
    )
    parser.add_argument(
        "--out-dependencies", help="Write extracted dependency versions JSON to this path"
    )
    parser.add_argument("--in-dependencies", help="Read dependency versions JSON from this path")
    parser.add_argument(
        "--parse-errors-file",
        help="If set, write per-file Java parse errors to this path (suppresses console spam)",
    )
    parser.add_argument(
        "--quiet-parse",
        action="store_true",
        help="Suppress per-file Java parse warnings on console; show only a summary",
    )
    return parser.parse_args()
