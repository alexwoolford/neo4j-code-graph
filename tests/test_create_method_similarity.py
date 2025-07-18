import sys
import types
from unittest import mock

# Stub graphdatascience before importing
sys.modules['graphdatascience'] = types.ModuleType('graphdatascience')
sys.modules['graphdatascience'].GraphDataScience = object
sys.modules['dotenv'] = types.ModuleType('dotenv')
sys.modules['dotenv'].load_dotenv = lambda override=True: None

import create_method_similarity as cms


def make_gds(modern=True):
    gds = mock.MagicMock()
    gds.graph = mock.MagicMock()
    graph_obj = mock.MagicMock()
    gds.graph.project.return_value = (graph_obj, None)
    if modern:
        gds.knn.write.return_value = None
    else:
        gds.knn.write.side_effect = [
            TypeError("missing 1 required positional argument"),
            None,
        ]
    return gds, graph_obj


def test_run_knn_modern_api():
    gds, _ = make_gds(modern=True)
    cms.run_knn(gds, top_k=3, cutoff=0.5)
    gds.knn.write.assert_called_once()
    args, kwargs = gds.knn.write.call_args
    assert kwargs['topK'] == 3
    assert kwargs['similarityCutoff'] == 0.5
    assert kwargs['writeRelationshipType'] == 'SIMILAR'
    assert not gds.graph.project.called


def test_run_knn_legacy_api():
    gds, graph_obj = make_gds(modern=False)
    cms.run_knn(gds, top_k=2, cutoff=0.1)
    assert gds.knn.write.call_count == 2
    gds.graph.drop.assert_called_with('methodGraph')
    gds.graph.project.assert_called_with(
        'methodGraph',
        {'Method': {'properties': 'embedding'}},
        '*'
    )
    graph_obj.drop.assert_called_once()


def test_create_index_executes_cypher():
    gds = mock.MagicMock()

    cms.create_index(gds)

    calls = gds.run_cypher.call_args_list
    assert len(calls) == 2

    first_call = calls[0]
    assert "CREATE VECTOR INDEX method_embeddings" in first_call.args[0]
    assert first_call.kwargs["params"] == {"dim": cms.EMBEDDING_DIM}

    second_call = calls[1]
    assert second_call.args[0] == "CALL db.awaitIndex('method_embeddings')"
