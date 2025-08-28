"""
Thin wrapper delegating to modular Prefect flow implementation.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from prefect import flow, get_run_logger

try:
    from src.pipeline.cli import parse_cli_args  # type: ignore
except Exception:  # pragma: no cover
    from pipeline.cli import parse_cli_args  # type: ignore

try:
    from src.pipeline.flows.core import build_args as core_build_args  # type: ignore
except Exception:  # pragma: no cover
    from pipeline.flows.core import build_args as core_build_args  # type: ignore

try:
    from src.pipeline.tasks.code_tasks import (  # type: ignore  # noqa: F401
        cleanup_artifacts_task,
        clone_repo_task,
        embed_files_task,
        embed_methods_task,
        extract_code_task,
    )
except Exception:  # pragma: no cover
    from pipeline.tasks.code_tasks import (  # type: ignore  # noqa: F401
        cleanup_artifacts_task,
        clone_repo_task,
        embed_files_task,
        embed_methods_task,
        extract_code_task,
    )

# Re-export Prefect tasks for legacy tests that patch attributes on this module
try:
    from src.pipeline.tasks.db_tasks import (  # type: ignore
        centrality_task,
        coupling_task,
        cve_task,
        git_history_task,
        louvain_task,
        setup_schema_task,
        similarity_task,
        write_graph_task,
    )
    from src.pipeline.tasks.db_tasks import (  # type: ignore
        selective_cleanup_task as _cleanup_task_impl,
    )
except Exception:  # pragma: no cover
    from pipeline.tasks.db_tasks import (  # type: ignore
        centrality_task,
        coupling_task,
        cve_task,
        git_history_task,
        louvain_task,
        setup_schema_task,
        similarity_task,
        write_graph_task,
    )
    from pipeline.tasks.db_tasks import (  # type: ignore
        selective_cleanup_task as _cleanup_task_impl,
    )

# Bind unified name for cleanup task
cleanup_task = _cleanup_task_impl  # noqa: F401

# Public exports to satisfy legacy tests that patch attributes on this module
__all__ = [
    "code_graph_flow",
    "main",
    "_build_args",
    "parse_cli_args",
    # DB tasks
    "setup_schema_task",
    "cleanup_task",
    "git_history_task",
    "write_graph_task",
    "similarity_task",
    "louvain_task",
    "centrality_task",
    "cve_task",
    "coupling_task",
    # Code tasks
    "clone_repo_task",
    "extract_code_task",
    "embed_files_task",
    "embed_methods_task",
    "cleanup_artifacts_task",
]


def _build_args(base: list[str], overrides: dict[str, object] | None = None) -> list[str]:
    """Legacy shim delegating to flows.core._build_args for tests.

    Keeps prior import path stable: src.pipeline.prefect_flow._build_args
    """
    return core_build_args(base, overrides)


@flow(name="neo4j-code-graph-pipeline")
def code_graph_flow(
    repo_url: str,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    cleanup: bool = True,
) -> None:
    """Flow wrapper that references tasks via this module for easy monkeypatching in tests."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    logger = get_run_logger()
    logger.info("Starting flow for repo: %s", repo_url)

    # Setup schema first
    setup_schema_task(uri, username, password, database)

    # Optional cleanup
    if cleanup:
        cleanup_task(uri, username, password, database)

    # Clone if needed
    p = Path(repo_url)
    if p.exists() and p.is_dir():
        repo_path = str(p)
    else:
        repo_path = clone_repo_task.submit(repo_url).result()

    # Build artifacts
    artifacts_dir = str(Path(tempfile.mkdtemp(prefix="cg_artifacts_")))
    extract_code_task(repo_path, artifacts_dir)
    embed_files_task(repo_path, artifacts_dir)
    embed_methods_task(repo_path, artifacts_dir)
    write_graph_task(repo_path, artifacts_dir, uri, username, password, database)
    cleanup_artifacts_task(artifacts_dir)

    # Git history
    git_history_task(repo_path, uri, username, password, database)

    # Coupling (call directly so tests can monkeypatch a plain function)
    coupling_task(uri, username, password, database)

    # Analytics (submit/async-compatible)
    similarity_task.submit(uri, username, password, database)
    louvain_task.submit(uri, username, password, database)
    centrality_task.submit(uri, username, password, database)
    cve_task.submit(uri, username, password, database)


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
