from __future__ import annotations

from prefect import get_run_logger

from src.pipeline.tasks.db_tasks import (
    centrality_task as T_centrality_task,
)
from src.pipeline.tasks.db_tasks import (
    cve_task as T_cve_task,
)
from src.pipeline.tasks.db_tasks import (
    louvain_task as T_louvain_task,
)
from src.pipeline.tasks.db_tasks import (
    similarity_task as T_similarity_task,
)


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
            _ = getattr(sim_state, "result", lambda: None)()
        except Exception:
            pass

        louv_state = T_louvain_task.submit(uri, username, password, database)
        try:
            _ = getattr(louv_state, "result", lambda: None)()
        except Exception:
            pass

        cent_state = T_centrality_task.submit(uri, username, password, database)
        try:
            _ = getattr(cent_state, "result", lambda: None)()
        except Exception:
            pass
    else:
        logger.warning("GDS not available; skipping similarity, Louvain, and centrality stages")

    cve_state = T_cve_task.submit(uri, username, password, database)
    try:
        cve_state.result()
    except Exception:
        raise
