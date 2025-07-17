import os
import sys
import shutil
from unittest.mock import MagicMock, patch
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

sys.modules.setdefault("torch", types.SimpleNamespace(no_grad=lambda: _NoGrad()))


import code_to_graph


def test_load_repo_executes_cypher(tmp_path):
    # Prepare a dummy repository with a single Java file
    repo_src = tmp_path / "src"
    repo_src.mkdir()
    java_file = repo_src / "Foo.java"
    java_file.write_text("class Foo { void bar() {} }")

    def fake_clone_from(url, dest):
        shutil.copytree(repo_src, dest, dirs_exist_ok=True)

    session_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session_mock
    driver_mock = MagicMock()
    driver_mock.session.return_value = session_cm

    with patch.object(code_to_graph.GraphDatabase, "driver", return_value=driver_mock) as mock_driver, \
         patch.object(code_to_graph.Repo, "clone_from", side_effect=fake_clone_from), \
         patch.object(code_to_graph, "AutoTokenizer"), \
         patch.object(code_to_graph, "AutoModel"), \
         patch.object(code_to_graph, "compute_embedding", return_value=[0.0]):
        driver = code_to_graph.GraphDatabase.driver("bolt://localhost:7687")
        code_to_graph.load_repo("dummy_url", driver)
        mock_driver.assert_called_once()

    queries = [c.args[0] for c in session_mock.run.call_args_list]
    assert any("MERGE (f:File" in q for q in queries)
    assert any("MERGE (m:Method" in q for q in queries)


def test_process_java_file_creates_directories(tmp_path):
    repo_root = tmp_path / "repo"
    file_dir = repo_root / "a" / "b"
    file_dir.mkdir(parents=True)
    java_file = file_dir / "Foo.java"
    java_file.write_text("class Foo { void bar() {} }")

    session_mock = MagicMock()

    with patch.object(code_to_graph, "compute_embedding", return_value=[0.0]):
        code_to_graph.process_java_file(
            java_file, MagicMock(), MagicMock(), session_mock, repo_root
        )

    queries = [c.args[0] for c in session_mock.run.call_args_list]
    assert any("MERGE (:Directory {path:$path})" in q for q in queries)
    assert any("MERGE (p:Directory" in q and "CONTAINS" in q for q in queries)
    assert any("MERGE (d:Directory" in q and "CONTAINS" in q and "File" in q for q in queries)
