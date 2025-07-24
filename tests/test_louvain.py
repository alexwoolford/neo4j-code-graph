import sys
import types
from unittest.mock import ANY, MagicMock

import pandas as pd

from src.analysis.similarity import run_louvain

# Stub heavy modules before importing the code under test
sys.modules.setdefault("graphdatascience", types.ModuleType("graphdatascience"))
sys.modules["graphdatascience"].GraphDataScience = object  # type: ignore[attr-defined]
sys.modules.setdefault("dotenv", types.ModuleType("dotenv"))
sys.modules["dotenv"].load_dotenv = lambda override=True: None  # type: ignore[attr-defined]


def test_run_louvain_creates_projection_and_runs():
    gds = MagicMock()
    gds.graph.exists.return_value = pd.Series({"exists": True})
    graph_obj = MagicMock()
    gds.graph.project.cypher.return_value = (graph_obj, None)

    run_louvain(gds, threshold=0.9, community_property="simComm")

    gds.graph.exists.assert_called_once_with("similarityGraph")
    gds.graph.drop.assert_called_once_with("similarityGraph")
    gds.graph.project.cypher.assert_called_once_with(
        "similarityGraph",
        "MATCH (m:Method) RETURN id(m) AS id",
        ANY,
        parameters={"threshold": 0.9},
    )
    gds.louvain.write.assert_called_once_with(graph_obj, writeProperty="simComm")
    graph_obj.drop.assert_called_once()


def test_run_louvain_without_existing_projection():
    gds = MagicMock()
    gds.graph.exists.return_value = pd.Series({"exists": False})
    graph_obj = MagicMock()
    gds.graph.project.cypher.return_value = (graph_obj, None)

    run_louvain(gds)

    gds.graph.drop.assert_not_called()
    gds.graph.project.cypher.assert_called_once()
    gds.louvain.write.assert_called_once()
    graph_obj.drop.assert_called_once()
