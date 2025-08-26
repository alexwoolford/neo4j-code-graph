from __future__ import annotations

import os
import tempfile
from pathlib import Path

from prefect import flow, get_run_logger

from src.pipeline.flows.similarity_flow import run_post_ingest_analytics
from src.pipeline.preflight import run_preflight
from src.pipeline.tasks.code_tasks import (
    cleanup_artifacts_task as T_cleanup_artifacts_task,
)
from src.pipeline.tasks.code_tasks import (
    clone_repo_task as T_clone_repo_task,
)
from src.pipeline.tasks.code_tasks import (
    embed_files_task as T_embed_files_task,
)
from src.pipeline.tasks.code_tasks import (
    embed_methods_task as T_embed_methods_task,
)
from src.pipeline.tasks.code_tasks import (
    extract_code_task as T_extract_code_task,
)
from src.pipeline.tasks.db_tasks import (
    cleanup_task as T_cleanup_task,
)
from src.pipeline.tasks.db_tasks import (
    git_history_task as T_git_history_task,
)
from src.pipeline.tasks.db_tasks import (
    setup_schema_task as T_setup_schema_task,
)
from src.pipeline.tasks.db_tasks import (
    write_graph_task as T_write_graph_task,
)


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
