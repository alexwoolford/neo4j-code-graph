import os
import sys
import types
from unittest.mock import MagicMock, patch

# Ensure src on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Stub heavy modules used during import for this test module
sys.modules.setdefault("tqdm", types.SimpleNamespace(tqdm=lambda *a, **k: a[0]))
sys.modules.setdefault("neo4j", types.SimpleNamespace(GraphDatabase=MagicMock()))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda **k: None))


def _create_file(i):
    path = f"dir{i}/File{i}.java"
    return {
        "path": path,
        "classes": [{"name": f"Class{i}", "file": path}],
        "interfaces": [],
        "methods": [],
        "imports": [],
    }


def test_file_node_batching():
    session = MagicMock()
    num_files = 2500
    files_data = [_create_file(i) for i in range(num_files)]
    file_embeds = [None] * num_files

    with patch.dict(sys.modules, {"javalang": types.ModuleType("javalang")}):
        import importlib

        from src.analysis import code_analysis as ca

        importlib.reload(ca)
        ca.bulk_create_nodes_and_relationships(session, files_data, file_embeds, [])

    # Reload module with real javalang for other tests
    import importlib

    from src.analysis import code_analysis as ca

    importlib.reload(ca)

    file_query = "MERGE (f:File"
    file_calls = [c for c in session.run.call_args_list if file_query in c.args[0]]
    assert len(file_calls) == 3
    for call in file_calls:
        assert len(call.kwargs["files"]) <= 1000

    dir_rel_query = "MERGE (parent)-[:CONTAINS]->(child)"
    dir_calls = [
        c
        for c in session.run.call_args_list
        if dir_rel_query in c.args[0] and "parent:Directory" in c.args[0]
    ]
    assert len(dir_calls) == 3
    for call in dir_calls:
        assert len(call.kwargs["rels"]) <= 1000

    class_query = "MERGE (c:Class"
    class_calls = [c for c in session.run.call_args_list if class_query in c.args[0]]
    assert len(class_calls) == 3
    for call in class_calls:
        assert len(call.kwargs["classes"]) <= 1000
