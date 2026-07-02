"""
Thin wrapper delegating to modular Prefect flow implementation.
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger

try:
    from src.pipeline.cli import parse_cli_args  # type: ignore
except Exception:  # pragma: no cover
    from pipeline.cli import parse_cli_args  # type: ignore

try:
    from src.pipeline.flows.core import build_args as core_build_args  # type: ignore
except Exception:  # pragma: no cover
    from pipeline.flows.core import build_args as core_build_args  # type: ignore

# Canonical post-ingest analytics stage (shared with flows.core)
try:
    from src.pipeline.flows.analytics_flow import run_post_ingest_analytics  # type: ignore
except Exception:  # pragma: no cover
    from pipeline.flows.analytics_flow import run_post_ingest_analytics  # type: ignore

# WP4 incremental ingest: provenance HWM + delta detection + subset patch.
try:
    from src.constants import SCHEMA_VERSION  # type: ignore
except Exception:  # pragma: no cover
    from constants import SCHEMA_VERSION  # type: ignore

try:
    from src.data.provenance import (  # type: ignore
        get_last_successful_ingest,
        normalize_repo_url,
        record_ingest_finish,
        record_ingest_start,
        tool_version,
    )
except Exception:  # pragma: no cover
    from data.provenance import (  # type: ignore
        get_last_successful_ingest,
        normalize_repo_url,
        record_ingest_finish,
        record_ingest_start,
        tool_version,
    )

try:
    from src.analysis.delta import (  # type: ignore
        changed_and_deleted,
        decide_ingest_mode,
        diff_changed_files,
        get_head_sha,
    )
except Exception:  # pragma: no cover
    from analysis.delta import (  # type: ignore
        changed_and_deleted,
        decide_ingest_mode,
        diff_changed_files,
        get_head_sha,
    )

try:
    from src.utils.common import create_neo4j_driver, resolve_neo4j_args  # type: ignore
except Exception:  # pragma: no cover
    from utils.common import create_neo4j_driver, resolve_neo4j_args  # type: ignore

try:
    from src.pipeline.tasks.code_tasks import (  # type: ignore  # noqa: F401
        cleanup_artifacts_task,
        clone_repo_task,
        extract_code_task,
    )
except Exception:  # pragma: no cover
    from pipeline.tasks.code_tasks import (  # type: ignore  # noqa: F401
        cleanup_artifacts_task,
        clone_repo_task,
        extract_code_task,
    )

# Re-export Prefect tasks for legacy tests that patch attributes on this module
try:  # Prefer src.* when available
    import src.pipeline.tasks.db_tasks as _db_tasks  # type: ignore
except Exception:  # pragma: no cover
    import pipeline.tasks.db_tasks as _db_tasks  # type: ignore

# Bind symbols once to avoid mypy redefinition warnings
centrality_task = _db_tasks.centrality_task  # type: ignore[attr-defined]
coupling_task = _db_tasks.coupling_task  # type: ignore[attr-defined]
cve_task = _db_tasks.cve_task  # type: ignore[attr-defined]
git_history_task = _db_tasks.git_history_task  # type: ignore[attr-defined]
setup_schema_task = _db_tasks.setup_schema_task  # type: ignore[attr-defined]
write_graph_task = _db_tasks.write_graph_task  # type: ignore[attr-defined]
patch_graph_task = _db_tasks.patch_graph_task  # type: ignore[attr-defined]
selective_cleanup_task = _db_tasks.selective_cleanup_task  # type: ignore[attr-defined]

# Bind unified name for cleanup task
cleanup_task = selective_cleanup_task  # noqa: F401

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
    "patch_graph_task",
    "centrality_task",
    "cve_task",
    "coupling_task",
    # Analytics stage
    "run_post_ingest_analytics",
    # Code tasks
    "clone_repo_task",
    "extract_code_task",
    "cleanup_artifacts_task",
]

_logger = logging.getLogger(__name__)


def _build_args(base: list[str], overrides: dict[str, object] | None = None) -> list[str]:
    """Legacy shim delegating to flows.core._build_args for tests.

    Keeps prior import path stable: src.pipeline.prefect_flow._build_args
    """
    return core_build_args(base, overrides)


@contextmanager
def _provenance_session(
    uri: str | None, username: str | None, password: str | None, database: str | None
):
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    driver = create_neo4j_driver(_uri, _user, _pwd)
    try:
        with driver.session(database=_db) as session:  # type: ignore[reportUnknownMemberType]
            yield session
    finally:
        try:
            driver.close()
        except Exception:
            pass


def _resolve_branch(repo_path: str) -> str:
    """Resolve the branch name used for provenance keys and git checkout."""
    env_branch = os.getenv("CODE_GRAPH_BRANCH")
    if env_branch:
        return env_branch
    try:
        from src.analysis.delta import _run_git  # type: ignore
    except Exception:  # pragma: no cover
        from analysis.delta import _run_git  # type: ignore
    try:
        proc = _run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        name = proc.stdout.strip()
        if name and name != "HEAD":
            return name
    except Exception:
        pass
    return "HEAD"


def _record_start_safe(
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    repo_url_norm: str,
    branch: str,
    head_sha: str | None,
    mode: str,
) -> str | None:
    """Best-effort provenance start; returns ingest_id or None if DB unreachable."""
    try:
        with _provenance_session(uri, username, password, database) as session:
            return record_ingest_start(
                session,
                repo_url_norm,
                branch,
                head_sha,
                mode,
                tool_version(),
                SCHEMA_VERSION,
            )
    except Exception as e:  # pragma: no cover - degrade gracefully without a DB
        _logger.warning("Could not record ingest start: %s", e)
        return None


def _record_finish_safe(
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    ingest_id: str | None,
    status: str,
) -> None:
    if not ingest_id:
        return
    try:
        with _provenance_session(uri, username, password, database) as session:
            record_ingest_finish(session, ingest_id, status)
    except Exception as e:  # pragma: no cover - degrade gracefully without a DB
        _logger.warning("Could not record ingest finish: %s", e)


def _run_full(
    repo_path: str,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    cleanup: bool,
    coupling_days: int | None,
) -> None:
    """Today's full ingest path (unchanged ordering; guarded by unit tests)."""
    # Optional cleanup (selective: GDS projections only)
    if cleanup:
        cleanup_task(uri, username, password, database)

    artifacts_dir = str(Path(tempfile.mkdtemp(prefix="cg_artifacts_")))
    extract_code_task(repo_path, artifacts_dir)
    # Optional: resolve build-time dependency versions for completeness
    try:
        from src.pipeline.tasks.code_tasks import resolve_build_dependencies_task  # type: ignore
    except Exception:  # pragma: no cover
        from pipeline.tasks.code_tasks import resolve_build_dependencies_task  # type: ignore
    if os.getenv("RESOLVE_BUILD_DEPS", "false").lower() in {"1", "true", "yes"}:
        resolve_build_dependencies_task(repo_path, artifacts_dir)
    write_graph_task(repo_path, artifacts_dir, uri, username, password, database)
    cleanup_artifacts_task(artifacts_dir)

    # Git history (full)
    git_history_task(repo_path, uri, username, password, database)

    # Coupling (call directly so tests can monkeypatch a plain function)
    coupling_task(uri, username, password, database, days=coupling_days)

    # Analytics: one canonical stage shared with flows.core.
    run_post_ingest_analytics(uri, username, password, database, gds_available=True)


def _run_incremental(
    repo_path: str,
    since_sha: str,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    coupling_days: int | None,
) -> None:
    """WP4 incremental path: subset extract -> footprint patch -> incr git -> analytics.

    Analytics refresh policy (WP4 Phase 6): pagerank/degree, calls_louvain and
    CVE all rerun every incremental run — they are global/idempotent and have no
    valid partial refresh (betweenness stays env-gated inside centrality_task).
    CO_CHANGED is rebuilt from scratch by coupling_task. The selective cleanup
    stage is intentionally SKIPPED (nothing to clean; a full wipe would defeat
    the point of an incremental patch).
    """
    logger = get_run_logger()
    delta = diff_changed_files(repo_path, since_sha, "HEAD")
    to_extract, removed = changed_and_deleted(delta)
    logger.info(
        "Incremental delta: %d files to (re)extract, %d removed at HEAD",
        len(to_extract),
        len(removed),
    )

    artifacts_dir = str(Path(tempfile.mkdtemp(prefix="cg_artifacts_")))
    # Subset extract: only changed/added files (deleted files are handled by the
    # footprint reconcile, not extraction). Dependency extraction stays global.
    extract_code_task(repo_path, artifacts_dir, files_subset=to_extract)
    patch_graph_task(
        repo_path,
        artifacts_dir,
        to_extract,
        removed,
        uri,
        username,
        password,
        database,
    )
    cleanup_artifacts_task(artifacts_dir)

    # Incremental git history: only commits since the previous HWM.
    git_history_task(repo_path, uri, username, password, database, since_sha=since_sha)

    # Coupling rebuild (CO_CHANGED is a pure function of CHANGED history).
    coupling_task(uri, username, password, database, days=coupling_days)

    # Global/idempotent analytics refresh (Phase 6).
    run_post_ingest_analytics(uri, username, password, database, gds_available=True)


@flow(name="neo4j-code-graph-pipeline")
def code_graph_flow(
    repo_url: str,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    cleanup: bool = True,
    coupling_days: int | None = None,
    incremental: bool = False,
) -> None:
    """Flow wrapper that references tasks via this module for easy monkeypatching in tests."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    logger = get_run_logger()
    logger.info("Starting flow for repo: %s (incremental=%s)", repo_url, incremental)
    # Also emit to standard application logger so it appears in neo4j-code-graph.log
    try:
        _logger.info("Starting flow for repo: %s", repo_url)
    except Exception:
        pass

    # Setup schema first
    setup_schema_task(uri, username, password, database)

    # Clone if needed
    p = Path(repo_url)
    if p.exists() and p.is_dir():
        repo_path = str(p)
    else:
        repo_path = clone_repo_task.submit(repo_url).result()

    # Provenance / high-water-mark bookkeeping
    branch = _resolve_branch(repo_path)
    head_sha = get_head_sha(repo_path)
    repo_url_norm = normalize_repo_url(repo_url)

    # Decide ingest mode. Incremental is opt-in; falls back to full when there is
    # no valid HWM (reason is logged by decide_ingest_mode).
    chosen_mode = "full"
    since_sha: str | None = None
    if incremental:
        last: dict[str, Any] | None = None
        try:
            with _provenance_session(uri, username, password, database) as session:
                last = get_last_successful_ingest(session, repo_url_norm, branch)
        except Exception as e:  # pragma: no cover - degrade to full without a DB
            logger.warning("Could not read last ingest HWM: %s", e)
            last = None
        chosen_mode, reason = decide_ingest_mode(
            repo_path, last, branch, SCHEMA_VERSION, head_sha, force_full=False
        )
        logger.info("Chosen ingest mode: %s (%s)", chosen_mode, reason)
        if chosen_mode == "incremental" and last is not None:
            since_sha = str(last.get("head_sha"))
    else:
        logger.info("Chosen ingest mode: full (incremental not requested)")

    ingest_id = _record_start_safe(
        uri, username, password, database, repo_url_norm, branch, head_sha, chosen_mode
    )

    try:
        if chosen_mode == "incremental" and since_sha:
            _run_incremental(repo_path, since_sha, uri, username, password, database, coupling_days)
        else:
            _run_full(repo_path, uri, username, password, database, cleanup, coupling_days)
    except Exception:
        _record_finish_safe(uri, username, password, database, ingest_id, "failed")
        raise
    else:
        _record_finish_safe(uri, username, password, database, ingest_id, "success")


def main() -> None:
    args = parse_cli_args()
    code_graph_flow(
        repo_url=args.repo_url,
        uri=args.uri,
        username=args.username,
        password=args.password,
        database=args.database,
        cleanup=not args.no_cleanup,
        coupling_days=args.coupling_days,
        incremental=bool(getattr(args, "incremental", False))
        and not bool(getattr(args, "full", False)),
    )


if __name__ == "__main__":
    main()
