"""
Prefect-based orchestration for the neo4j-code-graph pipeline.

This module exposes a Prefect flow that mirrors the end-to-end pipeline,
with opportunities for parallel execution and better observability.

Usage examples:
  - Local ad-hoc run:  python -m src.pipeline.prefect_flow --repo-url https://github.com/neo4j/graph-data-science
  - Via entrypoint:    code-graph-pipeline (to be wired) or `prefect run -p ...`
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.tasks import task_input_hash

# Import sibling packages in both contexts: installed package (top-level) and repo run (with 'src.')
try:
    from analysis.centrality import main as centrality_main
    from analysis.code_analysis import main as code_to_graph_main
    from analysis.git_analysis import main as git_history_main
    from analysis.similarity import main as similarity_main
    from data.schema_management import main as schema_main
    from security.cve_analysis import main as cve_main
    from utils.cleanup import main as cleanup_main
    from utils.common import setup_logging
except Exception:  # pragma: no cover - fallback path for direct repo execution
    from src.analysis.centrality import main as centrality_main  # type: ignore
    from src.analysis.code_analysis import main as code_to_graph_main  # type: ignore
    from src.analysis.git_analysis import main as git_history_main  # type: ignore
    from src.analysis.similarity import main as similarity_main  # type: ignore
    from src.data.schema_management import main as schema_main  # type: ignore
    from src.security.cve_analysis import main as cve_main  # type: ignore
    from src.utils.cleanup import main as cleanup_main  # type: ignore
    from src.utils.common import setup_logging  # type: ignore


def _build_args(
    base: list[str], overrides: dict[str, str | int | float | bool] | None = None
) -> list[str]:
    args = list(base)
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, bool):
                if value:
                    args.append(str(key))
            else:
                args.extend([str(key), str(value)])
    return args


@task(retries=1, retry_delay_seconds=5, cache_key_fn=task_input_hash)
def setup_schema_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Setting up database schema...")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    # Call CLI-style main with a sanitized argv
    base = ["prog"]
    overrides: dict[str, str] = {}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        schema_main()
    finally:
        sys.argv = old_argv


@task(retries=0)
def cleanup_task(
    confirm: bool,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
) -> None:
    logger = get_run_logger()
    logger.info("Cleaning up previous analysis (confirm=%s)...", confirm)
    # cleanup_main reads args via argparse; simulate non-interactive execution
    base = ["prog"]
    overrides: dict[str, str | bool] = {"--log-level": "INFO"}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    if confirm:
        overrides["--confirm"] = True
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        cleanup_main()
    finally:
        sys.argv = old_argv


@task(retries=1, retry_delay_seconds=5)
def clone_repo_task(repo_url: str) -> str:
    logger = get_run_logger()
    temp_dir = tempfile.mkdtemp()
    logger.info("Cloning %s into %s", repo_url, temp_dir)
    import git

    git.Repo.clone_from(repo_url, temp_dir)
    return temp_dir


@task(retries=1)
def code_to_graph_task(
    repo_path: str,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
) -> None:
    logger = get_run_logger()
    logger.info("Loading code structure + embeddings from %s", repo_path)
    # Build argv for the existing main
    base = ["prog", repo_path]
    overrides: dict[str, str] = {}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database

    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        code_to_graph_main()
    finally:
        sys.argv = old_argv


@task(retries=1)
def git_history_task(
    repo_path: str,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
) -> None:
    logger = get_run_logger()
    logger.info("Loading git history from %s", repo_path)
    base = ["prog", repo_path]
    overrides: dict[str, str] = {}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        git_history_main()
    finally:
        sys.argv = old_argv


@task(retries=1)
def similarity_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Running similarity (kNN + optional Louvain)")
    base = ["prog"]
    overrides: dict[str, str] = {"--top-k": "5", "--cutoff": "0.8"}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        similarity_main()
    finally:
        sys.argv = old_argv


@task(retries=1)
def louvain_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Running community detection (Louvain)")
    base = ["prog"]
    overrides: dict[str, str | bool | float] = {"--no-knn": True, "--community-threshold": 0.8}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        similarity_main()
    finally:
        sys.argv = old_argv


@task(retries=1)
def centrality_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Running centrality analysis")
    base = [
        "prog",
        "--algorithms",
        "pagerank",
        "betweenness",
        "degree",
        "--top-n",
        "15",
        "--write-back",
    ]
    overrides: dict[str, str] = {}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        centrality_main()
    finally:
        sys.argv = old_argv


@task(retries=0)
def cve_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Running CVE analysis (optional if NVD_API_KEY is present)")
    if not os.getenv("NVD_API_KEY"):
        logger.warning("NVD_API_KEY not set; skipping CVE analysis")
        return
    base = ["prog", "--risk-threshold", "7.0", "--max-hops", "4"]
    overrides: dict[str, str] = {}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        cve_main()
    finally:
        sys.argv = old_argv


@flow(name="neo4j-code-graph-pipeline")
def code_graph_flow(
    repo_url: str,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    cleanup: bool = True,
) -> None:
    """End-to-end pipeline as a Prefect flow."""
    setup_logging("INFO")
    logger = get_run_logger()
    logger.info("Starting flow for repo: %s", repo_url)

    setup_schema_task(uri, username, password, database)
    if cleanup:
        cleanup_task(cleanup, uri, username, password, database)

    # Clone or reuse a local path
    repo_path: str
    p = Path(repo_url)
    if p.exists() and p.is_dir():
        repo_path = str(p)
    else:
        repo_path = clone_repo_task.submit(repo_url).result()

    # Run code structure and git history in sequence (both require repo)
    code_to_graph_task(repo_path, uri, username, password, database)
    git_history_task(repo_path, uri, username, password, database)

    # Before similarity, clear existing SIMILAR relationships to avoid duplicates
    # Do it quickly with a small Cypher call via GDS client to ensure a clean slate
    try:
        from graphdatascience import GraphDataScience as _GDS  # local import

        gds = _GDS(
            uri if uri else "bolt://localhost:7687",
            auth=(username or "neo4j", password or "neo4j"),
            database=database or "neo4j",
            arrow=False,
        )
        gds.run_cypher("MATCH ()-[r:SIMILAR]-() DELETE r")
        gds.close()
    except Exception:
        pass

    # Run similarity then Louvain (explicit dependency). Capture futures and block at the end
    # to ensure the flow does not finish before downstream tasks complete.
    sim_state = similarity_task.submit(uri, username, password, database)
    louv_state = louvain_task.submit(uri, username, password, database, wait_for=[sim_state])
    cent_state = centrality_task.submit(uri, username, password, database, wait_for=[louv_state])

    # Optional CVE stage, after centrality
    cve_state = cve_task.submit(uri, username, password, database, wait_for=[cent_state])
    # Explicitly wait for the final task to complete to avoid early flow completion in some runners
    try:
        cve_state.result()
    except Exception:
        # The task/flow state will capture the exception; avoid masking it here
        raise
    logger.info("Flow complete")


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the neo4j-code-graph pipeline via Prefect")
    # Accept both optional flag and positional for repo URL for convenience
    parser.add_argument("--repo-url", dest="repo_url", help="Repository URL or local path")
    parser.add_argument("pos_repo_url", nargs="?", help="Repository URL or local path")
    parser.add_argument("--uri", help="Neo4j URI")
    parser.add_argument("--username", help="Neo4j username")
    parser.add_argument("--password", help="Neo4j password")
    parser.add_argument("--database", default="neo4j", help="Neo4j database")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip cleanup stage")
    args = parser.parse_args()
    # Normalize: prefer flag, fallback to positional
    if not (args.repo_url or args.pos_repo_url):
        parser.error("repo_url is required (use --repo-url or positional)")
    # attach normalized field for downstream use
    args.repo_url = args.repo_url or args.pos_repo_url
    return args


def main() -> None:
    args = parse_cli_args()
    code_graph_flow(
        repo_url=args.repo_url,
        uri=args.uri,
        username=args.username,
        password=args.password,
        database=args.database,
        cleanup=not args.no_cleanup,
    )


if __name__ == "__main__":
    main()
