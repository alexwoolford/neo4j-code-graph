import sys
import types
from unittest.mock import MagicMock
import pytest

# Stub heavy modules before importing the code under test
sys.modules.setdefault("graphdatascience", types.ModuleType("graphdatascience"))
sys.modules["graphdatascience"].GraphDataScience = object
sys.modules.setdefault("dotenv", types.ModuleType("dotenv"))
sys.modules["dotenv"].load_dotenv = lambda override=True: None

from create_method_similarity import run_knn


@pytest.mark.parametrize(
    "modern,top_k,cutoff",
    [
        (True, 3, 0.5),
        (False, 4, 0.7),
    ],
)
def test_run_knn(modern, top_k, cutoff):
    gds = MagicMock()
    gds.graph = MagicMock()
    graph_obj = MagicMock()
    gds.graph.project.return_value = (graph_obj, None)

    if modern:
        gds.knn.write.return_value = None
    else:
        gds.knn.write.side_effect = [
            TypeError("missing 1 required positional argument"),
            None,
        ]

    run_knn(gds, top_k=top_k, cutoff=cutoff)

    if modern:
        gds.knn.write.assert_called_once_with(
            nodeProjection={
                "Method": {
                    "properties": "embedding",
                    "where": "m.embedding IS NOT NULL",
                }
            },
            nodeProperties="embedding",
            topK=top_k,
            similarityCutoff=cutoff,
            writeRelationshipType="SIMILAR",
            writeProperty="score",
        )
        gds.graph.drop.assert_not_called()
        gds.graph.project.assert_not_called()
    else:
        assert gds.knn.write.call_count == 2
        first_call = gds.knn.write.call_args_list[0]
        assert "nodeProjection" in first_call.kwargs
        gds.graph.drop.assert_called_with("methodGraph")
        gds.graph.project.assert_called_with(
            "methodGraph",
            {"Method": {"properties": "embedding", "where": "m.embedding IS NOT NULL"}},
            "*",
        )
        graph_obj.drop.assert_called_once()
        second_call = gds.knn.write.call_args_list[1]
        assert second_call.args[0] is graph_obj
        assert "nodeProjection" not in second_call.kwargs


def test_run_knn_filters_missing_embeddings():
    gds = MagicMock()
    gds.graph = MagicMock()
    graph_obj = MagicMock()
    gds.graph.project.return_value = (graph_obj, None)
    gds.knn.write.side_effect = [
        TypeError("missing 1 required positional argument"),
        None,
    ]

    run_knn(gds)

    assert gds.knn.write.call_count == 2
    gds.graph.project.assert_called_with(
        "methodGraph",
        {"Method": {"properties": "embedding", "where": "m.embedding IS NOT NULL"}},
        "*",
    )
