from __future__ import annotations

import os
import tempfile

# Single-definition import strategy to satisfy both CLI execution forms
from importlib import import_module
from pathlib import Path

from prefect import flow, get_run_logger

try:
    _CT = import_module("src.pipeline.tasks.code_tasks")
    _DT = import_module("src.pipeline.tasks.db_tasks")
    _SIM = import_module("src.pipeline.flows.similarity_flow")
    _PREF = import_module("src.pipeline.preflight")
except Exception:  # pragma: no cover - script execution path
    _CT = import_module("pipeline.tasks.code_tasks")
    _DT = import_module("pipeline.tasks.db_tasks")
    _SIM = import_module("pipeline.flows.similarity_flow")
    _PREF = import_module("pipeline.preflight")


# Bind names once
def run_post_ingest_analytics(*args, **kwargs):
    return _SIM.run_post_ingest_analytics(*args, **kwargs)


def run_preflight(*args, **kwargs):
    return _PREF.run_preflight(*args, **kwargs)


T_cleanup_artifacts_task = _CT.cleanup_artifacts_task
T_clone_repo_task = _CT.clone_repo_task
T_embed_files_task = _CT.embed_files_task
T_embed_methods_task = _CT.embed_methods_task
T_extract_code_task = _CT.extract_code_task
T_cleanup_task = _DT.cleanup_task
T_git_history_task = _DT.git_history_task
T_setup_schema_task = _DT.setup_schema_task
T_write_graph_task = _DT.write_graph_task


def build_args(base: list[str], overrides: dict[str, object] | None = None) -> list[str]:
    args = list(base)
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, bool):
                if value:
                    args.append(str(key))
            else:
                args.extend([str(key), str(value)])
    return args


@flow(name="neo4j-code-graph-pipeline")
def code_graph_flow(
    repo_url: str,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    cleanup: bool = True,
) -> None:
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    logger = get_run_logger()
    logger.info("Starting flow for repo: %s", repo_url)

    caps: dict[str, object] = run_preflight(uri, username, password, database)
    T_setup_schema_task(uri, username, password, database)
    gds_info_obj = caps.get("gds")
    gds_info: dict[str, object] = gds_info_obj if isinstance(gds_info_obj, dict) else {}
    gds_ok = bool(gds_info.get("available", False))
    if cleanup:
        T_cleanup_task(uri, username, password, database)

    p = Path(repo_url)
    if p.exists() and p.is_dir():
        repo_path = str(p)
    else:
        repo_path = T_clone_repo_task.submit(repo_url).result()

    artifacts_dir = str(Path(tempfile.mkdtemp(prefix="cg_artifacts_")))
    T_extract_code_task(repo_path, artifacts_dir)
    T_embed_files_task(repo_path, artifacts_dir)
    T_embed_methods_task(repo_path, artifacts_dir)
    T_write_graph_task(repo_path, artifacts_dir, uri, username, password, database)
    T_cleanup_artifacts_task(artifacts_dir)

    T_git_history_task(repo_path, uri, username, password, database)

    from prefect import get_run_logger as _get_log

    _get_log().info("Summary and intent similarity stages are not part of this flow")
    run_post_ingest_analytics(uri, username, password, database, gds_available=gds_ok)
