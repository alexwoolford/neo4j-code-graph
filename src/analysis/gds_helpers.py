#!/usr/bin/env python3

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_method_calls_projection(
    gds: Any, graph_name: str = "method_call_graph"
) -> tuple[Any, dict]:
    """Create or recreate a Method/CALLS projection and return (graph, meta).

    - Drops existing projection with the same name if present
    - Uses NATURAL orientation for directed CALLS relationships
    """
    try:
        gds.graph.drop(graph_name)
        logger.info("Dropped existing graph projection: %s", graph_name)
    except Exception:
        pass

    logger.info("Creating method call graph projection: %s", graph_name)
    G, meta = gds.graph.project(
        graph_name,
        ["Method"],
        {"CALLS": {"orientation": "NATURAL"}},
    )
    return G, meta


__all__ = ["create_method_calls_projection"]
