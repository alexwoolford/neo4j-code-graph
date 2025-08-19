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
from collections.abc import Mapping
from pathlib import Path

from prefect import flow, get_run_logger, task

# Import sibling packages in both contexts: installed package (top-level) and repo run (with 'src.')
try:
    from analysis.centrality import main as centrality_main
    from analysis.code_analysis import main as code_to_graph_main
    from analysis.git_analysis import main as git_history_main
    from analysis.similarity import main as similarity_main
    from analysis.temporal_analysis import main as temporal_main
    from data.schema_management import main as schema_main
    from security.cve_analysis import main as cve_main
    from utils.common import setup_logging
except Exception:  # pragma: no cover - fallback path for direct repo execution
    from src.analysis.centrality import main as centrality_main  # type: ignore
    from src.analysis.code_analysis import main as code_to_graph_main  # type: ignore
    from src.analysis.git_analysis import main as git_history_main  # type: ignore
    from src.analysis.similarity import main as similarity_main  # type: ignore
    from src.analysis.temporal_analysis import main as temporal_main  # type: ignore
    from src.data.schema_management import main as schema_main  # type: ignore
    from src.security.cve_analysis import main as cve_main  # type: ignore
    from src.utils.common import setup_logging  # type: ignore


def _build_args(base: list[str], overrides: Mapping[str, object] | None = None) -> list[str]:
    args = list(base)
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, bool):
                if value:
                    args.append(str(key))
            else:
                args.extend([str(key), str(value)])
    return args


@task(retries=1, retry_delay_seconds=5)
def setup_schema_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Setting up database schema...")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    # Call CLI-style main with a sanitized argv
    base = ["prog"]
    overrides: dict[str, object] = {}
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
def selective_cleanup_task(
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
) -> None:
    logger = get_run_logger()
    logger.info("Selective cleanup before similarity/community stages...")
    # Call the cleanup CLI in selective mode to remove analysis artifacts only
    base = ["prog", "--log-level", "INFO"]
    overrides: dict[str, object] = {}
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
        # We pass no flags; the cleanup script's default path now exposes a selective cleanup helper
        sys.argv = _build_args(base, overrides)
        # Import and call the selective cleanup flow directly to avoid CLI arg plumbing
        try:
            from src.utils.cleanup import selective_cleanup as _sel
        except Exception:
            from utils.cleanup import selective_cleanup as _sel  # type: ignore
        # Import driver helper in both contexts (installed package vs repo path)
        try:
            from utils.common import create_neo4j_driver as _drv
        except Exception:  # pragma: no cover - fallback when running as module
            from src.utils.common import create_neo4j_driver as _drv  # type: ignore

        with _drv(uri or "", username or "", password or "") as driver:
            with driver.session(database=database) as session:
                _sel(session, dry_run=False)
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


@task(retries=1)
def write_graph_task(
    repo_path: str,
    artifacts_dir: str,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
) -> None:
    logger = get_run_logger()
    logger.info("Writing extracted data and embeddings to Neo4j from %s", artifacts_dir)
    in_files = str(Path(artifacts_dir) / "files_data.json")
    in_deps = str(Path(artifacts_dir) / "dependencies.json")
    in_file_emb = str(Path(artifacts_dir) / "file_embeddings.npy")
    in_method_emb = str(Path(artifacts_dir) / "method_embeddings.npy")

    base = [
        "prog",
        repo_path,
        "--skip-embed",
        "--in-files-data",
        in_files,
        "--in-dependencies",
        in_deps,
        "--in-file-embeddings",
        in_file_emb,
        "--in-method-embeddings",
        in_method_emb,
    ]
    overrides: dict[str, object] = {}
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

    # Observability: log how many methods have embeddings set
    try:
        from graphdatascience import GraphDataScience as _GDS  # type: ignore

        # Resolve connection consistently; prefer explicit args if provided
        if uri and username and password:
            _uri, _user, _pwd, _db = uri, username, password, database
        else:
            from src.utils.neo4j_utils import get_neo4j_config as _get_cfg  # type: ignore

            _uri, _user, _pwd, _db = _get_cfg()
            if database:
                _db = database

        from src.constants import EMBEDDING_PROPERTY as _EMB

        gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
        df = gds.run_cypher(f"MATCH (m:Method) WHERE m.{_EMB} IS NOT NULL RETURN count(m) AS c")
        count = int(df.iloc[0]["c"]) if not df.empty else 0
        logger.info("Methods with embeddings (%s): %d", _EMB, count)
        gds.close()
    except Exception:
        # Best-effort logging only; do not fail the pipeline here
        pass


@task(retries=0)
def cleanup_artifacts_task(artifacts_dir: str) -> None:
    logger = get_run_logger()
    try:
        import shutil

        shutil.rmtree(artifacts_dir, ignore_errors=True)
        logger.info("Cleaned up artifacts directory: %s", artifacts_dir)
    except Exception as e:
        logger.warning("Failed to remove artifacts directory %s: %s", artifacts_dir, e)


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
    overrides: dict[str, object] = {}
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


## Removed summarization and intent similarity tasks


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
    overrides: dict[str, object] = {}
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
def coupling_task(
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    min_support: int = 5,
    confidence_threshold: float = 0.6,
) -> None:
    logger = get_run_logger()
    logger.info(
        "Running change coupling (min_support=%d, confidence>=%.2f)",
        min_support,
        confidence_threshold,
    )
    base = [
        "prog",
        "coupling",
        "--create-relationships",
        "--min-support",
        str(min_support),
        "--confidence-threshold",
        str(confidence_threshold),
    ]
    overrides: dict[str, object] = {}
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
        temporal_main()
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
    # Silence HF tokenizers fork warnings in child tasks
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    logger = get_run_logger()
    logger.info("Starting flow for repo: %s", repo_url)

    setup_schema_task(uri, username, password, database)
    if cleanup:
        selective_cleanup_task(uri, username, password, database)

    # Clone or reuse a local path
    repo_path: str
    p = Path(repo_url)
    if p.exists() and p.is_dir():
        repo_path = str(p)
    else:
        repo_path = clone_repo_task.submit(repo_url).result()

    # Run code structure in granular steps with artifacts
    artifacts_dir = str(Path(tempfile.mkdtemp(prefix="cg_artifacts_")))
    extract_code_task(repo_path, artifacts_dir)
    embed_files_task(repo_path, artifacts_dir)
    embed_methods_task(repo_path, artifacts_dir)
    write_graph_task(repo_path, artifacts_dir, uri, username, password, database)
    cleanup_artifacts_task(artifacts_dir)

    # Then run git history
    git_history_task(repo_path, uri, username, password, database)

    # Create CO_CHANGED relationships from commit history before similarity
    coupling_task(uri, username, password, database)

    # Summaries/intent stages removed
    logger.info("Summary and intent similarity stages are not part of this flow")

    # Redundant explicit SIMILAR purge removed; selective_cleanup_task already handles analysis artifacts

    # Run similarity then Louvain (explicit dependency). Capture futures and block at the end
    # to ensure the flow does not finish before downstream tasks complete.
    sim_state = similarity_task.submit(uri, username, password, database)
    louv_state = louvain_task.submit(uri, username, password, database, wait_for=sim_state)
    cent_state = centrality_task.submit(uri, username, password, database, wait_for=louv_state)

    # Optional CVE stage, after centrality
    cve_state = cve_task.submit(uri, username, password, database, wait_for=cent_state)
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
    # Do not default database here; let tooling read from .env / env via add_common_args
    parser.add_argument("--database", help="Neo4j database (overrides .env if set)")
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
