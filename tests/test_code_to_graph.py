import os
import sys
from unittest.mock import MagicMock
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Provide stub modules for heavy dependencies so that code_to_graph can be
# imported without installing transformers or torch.
sys.modules.setdefault(
    "transformers",
    types.SimpleNamespace(AutoTokenizer=MagicMock(), AutoModel=MagicMock()),
)


class _NoGrad:
    def __enter__(self):
        pass

    def __exit__(self, *exc):
        pass


sys.modules.setdefault(
    "torch",
    types.SimpleNamespace(
        no_grad=lambda: _NoGrad(),
        cuda=types.SimpleNamespace(is_available=lambda: False),
        backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False)),
        device=lambda x: f"device({x})",
    ),
)

sys.modules.setdefault("git", types.SimpleNamespace(Repo=MagicMock()))
sys.modules.setdefault("neo4j", types.SimpleNamespace(GraphDatabase=MagicMock()))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda **k: None))


import code_to_graph




