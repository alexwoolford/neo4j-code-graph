from __future__ import annotations

from importlib import import_module as _imp

from prefect import get_run_logger

try:
    _dbt = _imp("src.pipeline.tasks.db_tasks")
except Exception:  # pragma: no cover
    _dbt = _imp("pipeline.tasks.db_tasks")

T_centrality_task = _dbt.centrality_task
T_cve_task = _dbt.cve_task
T_louvain_task = _dbt.louvain_task
T_similarity_task = _dbt.similarity_task


def run_post_ingest_analytics(
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    gds_available: bool,
) -> None:
    logger = get_run_logger()
    if gds_available:
        sim_state = T_similarity_task.submit(uri, username, password, database)
        try:
            if hasattr(sim_state, "result"):
                sim_state.result()  # type: ignore[attr-defined]
        except Exception:
            pass

        louv_state = T_louvain_task.submit(uri, username, password, database)
        try:
            if hasattr(louv_state, "result"):
                louv_state.result()  # type: ignore[attr-defined]
        except Exception:
            pass

        cent_state = T_centrality_task.submit(uri, username, password, database)
        try:
            if hasattr(cent_state, "result"):
                cent_state.result()  # type: ignore[attr-defined]
        except Exception:
            pass
    else:
        logger.warning("GDS not available; skipping similarity, Louvain, and centrality stages")

    cve_state = T_cve_task.submit(uri, username, password, database)
    try:
        cve_state.result()
    except Exception:
        raise
