import sys
import types
from unittest.mock import MagicMock

import pandas as pd

from src.analysis.similarity import run_knn

# Stub heavy modules before importing the code under test
sys.modules.setdefault("graphdatascience", types.ModuleType("graphdatascience"))
sys.modules["graphdatascience"].GraphDataScience = object
sys.modules.setdefault("dotenv", types.ModuleType("dotenv"))
sys.modules["dotenv"].load_dotenv = lambda override=True: None


def test_run_knn_creates_projection_and_runs():
    gds = MagicMock()
    gds.run_cypher.return_value = pd.DataFrame([{"missing": 2}])
    gds.graph.exists.return_value = pd.Series({"exists": True})
    graph_obj = MagicMock()
    gds.graph.project.cypher.return_value = (graph_obj, None)

    run_knn(gds, top_k=3, cutoff=0.5)

    gds.run_cypher.assert_called_once_with(
        "MATCH (m:Method) WHERE m.embedding IS NULL RETURN count(m) AS missing"
    )
    gds.graph.exists.assert_called_once_with("methodGraph")
    gds.graph.drop.assert_called_once_with("methodGraph")
    gds.graph.project.cypher.assert_called_once_with(
        "methodGraph",
        (
            "MATCH (m:Method) WHERE m.embedding IS NOT NULL "
            "RETURN id(m) AS id, m.embedding AS embedding"
        ),
        "RETURN null AS source, null AS target LIMIT 0",
    )
    gds.knn.write.assert_called_once_with(
        graph_obj,
        nodeProperties="embedding",
        topK=3,
        similarityCutoff=0.5,
        writeRelationshipType="SIMILAR",
        writeProperty="score",
    )
    graph_obj.drop.assert_called_once()


def test_run_knn_without_existing_projection():
    gds = MagicMock()
    gds.run_cypher.return_value = pd.DataFrame([{"missing": 0}])
    gds.graph.exists.return_value = pd.Series({"exists": False})
    graph_obj = MagicMock()
    gds.graph.project.cypher.return_value = (graph_obj, None)

    run_knn(gds)

    gds.graph.drop.assert_not_called()
    gds.graph.project.cypher.assert_called_once()
    gds.knn.write.assert_called_once()
    graph_obj.drop.assert_called_once()
