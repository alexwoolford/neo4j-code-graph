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


def test_code_to_graph_imports():
    """Test that code_to_graph module can be imported and has expected functions."""
    try:
        import code_to_graph

        # Check for key functions
        expected_functions = [
            "extract_file_data",
            "bulk_create_nodes_and_relationships",
            "compute_embeddings_bulk",
            "main"
        ]

        for func_name in expected_functions:
            assert hasattr(code_to_graph, func_name), \
                f"Missing function {func_name} in code_to_graph"

        print("✅ code_to_graph module imports successfully")
        return True

    except ImportError as e:
        print(f"❌ Failed to import code_to_graph: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing code_to_graph: {e}")
        return False


if __name__ == "__main__":
    success = test_code_to_graph_imports()
    sys.exit(0 if success else 1)
