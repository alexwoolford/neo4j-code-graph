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
        gds.run_cypher(
            "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName", name=graph_name
        )
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


def enrich_node_ids_with_method_details(gds: Any, node_ids: list[int]) -> Any:
    """Return a DataFrame with method details for given GDS node ids.

    Columns: nodeId, method_name, class_name, file
    """
    if not node_ids:
        import pandas as pd  # type: ignore

        return pd.DataFrame(columns=["nodeId", "method_name", "class_name", "file"])  # type: ignore

    query = (
        "UNWIND $nodeIds as nodeId "
        "WITH nodeId, gds.util.asNode(nodeId) as m "
        "RETURN nodeId, m.name as method_name, m.class_name as class_name, m.file as file"
    )
    return gds.run_cypher(query, {"nodeIds": node_ids})


__all__.append("enrich_node_ids_with_method_details")


def create_similarity_projection(
    gds: Any, threshold: float = 0.8, graph_name: str = "similarityGraph"
) -> tuple[Any, Any]:
    """Create a projection over SIMILAR relationships with score threshold.

    Returns (graph, meta) from project.cypher
    """
    try:
        gds.run_cypher(
            "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName", name=graph_name
        )
    except Exception:
        pass

    node_query = "MATCH (m:Method) RETURN id(m) AS id"
    rel_query = (
        "MATCH (m1:Method)-[s:SIMILAR]->(m2:Method) "
        "WHERE s.score >= $threshold "
        "RETURN id(m1) AS source, id(m2) AS target, s.score AS score"
    )
    return gds.graph.project.cypher(
        graph_name, node_query, rel_query, parameters={"threshold": threshold}
    )


__all__.append("create_similarity_projection")
