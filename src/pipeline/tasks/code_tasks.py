from __future__ import annotations

import tempfile
from pathlib import Path

from prefect import get_run_logger, task

from src.analysis.code_analysis import main as code_to_graph_main


@task(retries=1)
def clone_repo_task(repo_url: str) -> str:
    logger = get_run_logger()
    temp_dir = tempfile.mkdtemp()
    logger.info("Cloning %s into %s", repo_url, temp_dir)
    import git

    git.Repo.clone_from(repo_url, temp_dir)
    return temp_dir


@task(retries=1)
def extract_code_task(repo_path: str, out_dir: str) -> str:
    logger = get_run_logger()
    logger.info("Extracting code structure from %s", repo_path)
    out_files = str(Path(out_dir) / "files_data.json")
    out_deps = str(Path(out_dir) / "dependencies.json")
    base = [
        "prog",
        repo_path,
        "--skip-embed",
        "--skip-db",
        "--out-files-data",
        out_files,
        "--out-dependencies",
        out_deps,
    ]
    import sys

    old_argv = sys.argv
    try:
        sys.argv = base
        code_to_graph_main()
    finally:
        sys.argv = old_argv
    return out_dir


@task(retries=1)
def embed_files_task(repo_path: str, artifacts_dir: str) -> str:
    logger = get_run_logger()
    logger.info("Computing file embeddings for %s", repo_path)
    in_files = str(Path(artifacts_dir) / "files_data.json")
    out_file_emb = str(Path(artifacts_dir) / "file_embeddings.npy")
    base = [
        "prog",
        repo_path,
        "--skip-db",
        "--embed-target",
        "files",
        "--in-files-data",
        in_files,
        "--out-file-embeddings",
        out_file_emb,
    ]
    import sys

    old_argv = sys.argv
    try:
        sys.argv = base
        code_to_graph_main()
    finally:
        sys.argv = old_argv
    return artifacts_dir


@task(retries=0)
def cleanup_artifacts_task(artifacts_dir: str) -> None:
    logger = get_run_logger()
    try:
        import shutil

        shutil.rmtree(artifacts_dir, ignore_errors=True)
        logger.info("Cleaned up artifacts directory: %s", artifacts_dir)
    except Exception as e:  # pragma: no cover - non-critical cleanup
        logger.warning("Failed to remove artifacts directory %s: %s", artifacts_dir, e)


@task(retries=1)
def embed_methods_task(repo_path: str, artifacts_dir: str) -> str:
    logger = get_run_logger()
    logger.info("Computing method embeddings for %s", repo_path)
    in_files = str(Path(artifacts_dir) / "files_data.json")
    out_method_emb = str(Path(artifacts_dir) / "method_embeddings.npy")
    base = [
        "prog",
        repo_path,
        "--skip-db",
        "--embed-target",
        "methods",
        "--in-files-data",
        in_files,
        "--out-method-embeddings",
        out_method_emb,
    ]
    import sys

    old_argv = sys.argv
    try:
        sys.argv = base
        code_to_graph_main()
    finally:
        sys.argv = old_argv
    return artifacts_dir
