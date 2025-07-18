import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from create_method_similarity import run_knn


def test_run_knn_modern_api():
    gds = MagicMock()
    gds.graph = MagicMock()
    run_knn(gds, top_k=3, cutoff=0.5)
    gds.knn.write.assert_called_once_with(
        nodeProjection="Method",
        nodeProperties="embedding",
        topK=3,
        similarityCutoff=0.5,
        writeRelationshipType="SIMILAR",
        writeProperty="score",
    )
    gds.graph.drop.assert_not_called()
    gds.graph.project.assert_not_called()


def test_run_knn_legacy_api():
    gds = MagicMock()
    graph_mock = MagicMock()
    gds.graph.project.return_value = (graph_mock, None)
    gds.knn.write.side_effect = [
        TypeError("missing 1 required positional argument"),
        None,
    ]

    run_knn(gds, top_k=4, cutoff=0.7)

    assert gds.knn.write.call_count == 2
    first_call = gds.knn.write.call_args_list[0]
    assert "nodeProjection" in first_call.kwargs
    gds.graph.drop.assert_called_with("methodGraph")
    gds.graph.project.assert_called_with(
        "methodGraph",
        {"Method": {"properties": "embedding"}},
        "*",
    )
    graph_mock.drop.assert_called_once()
    second_call = gds.knn.write.call_args_list[1]
    assert second_call.args[0] is graph_mock
    assert "nodeProjection" not in second_call.kwargs
