"""
Thin wrapper delegating to modular Prefect flow implementation.
"""

from __future__ import annotations

try:
    from src.pipeline.cli import parse_cli_args  # type: ignore
except Exception:  # pragma: no cover
    from pipeline.cli import parse_cli_args  # type: ignore

try:
    from src.pipeline.flows.core import build_args as core_build_args  # type: ignore
    from src.pipeline.flows.core import code_graph_flow  # type: ignore
except Exception:  # pragma: no cover
    from pipeline.flows.core import build_args as core_build_args  # type: ignore
    from pipeline.flows.core import code_graph_flow  # type: ignore

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
