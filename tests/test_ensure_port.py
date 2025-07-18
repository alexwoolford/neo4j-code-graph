import importlib
import os
import sys
import types
from unittest.mock import MagicMock, patch
import pytest

# Ensure project root is on the import path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _stub_module(name, attrs=None):
    mod = types.ModuleType(name)
    for attr in attrs or []:
        setattr(mod, attr, MagicMock())
    return mod

HEAVY_MODULES = {
    "git": _stub_module("git", ["Repo"]),
    "neo4j": _stub_module("neo4j", ["GraphDatabase"]),
    "transformers": _stub_module(
        "transformers",
        ["AutoTokenizer", "AutoModel"],
    ),
    "torch": _stub_module("torch"),
    "javalang": _stub_module("javalang"),
    "dotenv": _stub_module("dotenv", ["load_dotenv"]),
    "graphdatascience": _stub_module("graphdatascience", ["GraphDataScience"]),
}


@pytest.mark.parametrize(
    "module_name",
    ["code_to_graph", "create_method_similarity"],
)
@pytest.mark.parametrize(
    "uri, expected",
    [
        ("bolt://localhost:7687", "bolt://localhost:7687"),
        ("bolt://localhost", "bolt://localhost:7687"),
        ("neo4j://user:pass@host", "neo4j://user:pass@host:7687"),
        ("neo4j://user@host:9999", "neo4j://user@host:9999"),
    ],
)
def test_ensure_port(module_name, uri, expected):
    with patch.dict(sys.modules, HEAVY_MODULES):
        module = importlib.import_module(module_name)
        assert module.ensure_port(uri) == expected
