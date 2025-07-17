import os
import sys
import types
from unittest.mock import MagicMock, patch
import importlib
import pytest


@pytest.fixture(autouse=True)
def mock_heavy_deps():
    """Provide dummy versions of optional heavy dependencies."""
    heavy = {
        "git": types.SimpleNamespace(Repo=MagicMock()),
        "neo4j": types.SimpleNamespace(GraphDatabase=MagicMock()),
        "graphdatascience": types.SimpleNamespace(GraphDataScience=MagicMock()),
        "transformers": types.SimpleNamespace(
            AutoTokenizer=MagicMock(), AutoModel=MagicMock()
        ),
        "torch": MagicMock(),
        "javalang": MagicMock(),
        "dotenv": MagicMock(),
    }
    with patch.dict(sys.modules, heavy):
        yield


@pytest.fixture
def modules():
    """Import the application modules with heavy deps mocked."""
    code_to_graph = importlib.import_module("code_to_graph")
    create_method_similarity = importlib.import_module(
        "create_method_similarity"
    )
    return code_to_graph, create_method_similarity


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils import ensure_port


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("bolt://localhost", "bolt://localhost:7687"),
        ("bolt://localhost:9999", "bolt://localhost:9999"),
        ("bolt://user:pass@localhost", "bolt://user:pass@localhost:7687"),
    ],
)
def test_ensure_port(uri, expected, modules):
    code_to_graph, create_method_similarity = modules
    assert ensure_port(uri) == expected
    assert code_to_graph.ensure_port(uri) == expected
    assert create_method_similarity.ensure_port(uri) == expected
