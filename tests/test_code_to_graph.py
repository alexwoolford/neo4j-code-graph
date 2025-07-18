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


sys.modules.setdefault(
    "torch",
    types.SimpleNamespace(no_grad=lambda: _NoGrad()),
)

sys.modules.setdefault("git", types.SimpleNamespace(Repo=MagicMock()))
sys.modules.setdefault("neo4j", types.SimpleNamespace(GraphDatabase=MagicMock()))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda **k: None))


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

    with patch.object(
        code_to_graph.GraphDatabase,
        "driver",
        return_value=driver_mock,
    ) as mock_driver, patch.object(
        code_to_graph.Repo,
        "clone_from",
        side_effect=fake_clone_from,
    ), patch.object(
        code_to_graph, "AutoTokenizer"
    ), patch.object(
        code_to_graph,
        "AutoModel",
    ), patch.object(
        code_to_graph,
        "compute_embedding",
        return_value=[0.0],
    ):
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

    calls = session_mock.run.call_args_list
    dir_paths = [
        c.kwargs["path"] for c in calls if c.args[0].startswith("MERGE (:Directory")
    ]
    assert dir_paths == ["a", "a/b"]

    assert any(
        "path:''" in c.args[0] and c.kwargs.get("child") == "a"
        for c in calls
        if "CONTAINS" in c.args[0]
    )

    assert any(
        c.kwargs.get("parent") == "a" and c.kwargs.get("child") == "a/b"
        for c in calls
        if "CONTAINS" in c.args[0] and "child" in c.kwargs
    )

    assert any(
        c.kwargs.get("dir") == "a/b" and c.kwargs.get("file") == "a/b/Foo.java"
        for c in calls
        if "File" in c.args[0] and "dir" in c.kwargs
    )


def test_process_java_file_creates_calls(tmp_path):
    java_file = tmp_path / "Foo.java"
    java_file.write_text("class Foo { void bar() { baz(); } void baz() {} }")

    session_mock = MagicMock()

    with patch.object(code_to_graph, "compute_embedding", return_value=[0.0]):
        code_to_graph.process_java_file(
            java_file, MagicMock(), MagicMock(), session_mock, tmp_path
        )

    call_params = [c for c in session_mock.run.call_args_list if "CALLS" in c.args[0]]
    assert call_params
    params = call_params[0].args[1]
    assert params.get("caller_name") == "bar"
    assert params.get("callee_name") == "baz"


def test_main_accepts_optional_arguments(monkeypatch):
    args = types.SimpleNamespace(
        repo_url="https://example.com/repo.git",
        uri="bolt://example",
        username="neo4j",
        password="secret",
        database="testdb",
        log_level="INFO",
    )

    driver_instance = MagicMock()
    monkeypatch.setattr(code_to_graph, "parse_args", lambda: args)
    ensure_port_mock = MagicMock(return_value="bolt://example:9999")
    monkeypatch.setattr(code_to_graph, "ensure_port", ensure_port_mock)
    monkeypatch.setattr(
        code_to_graph.GraphDatabase, "driver", MagicMock(return_value=driver_instance)
    )
    load_repo_mock = MagicMock()
    monkeypatch.setattr(code_to_graph, "load_repo", load_repo_mock)

    code_to_graph.main()

    ensure_port_mock.assert_called_once_with(args.uri)
    code_to_graph.GraphDatabase.driver.assert_called_once_with(
        "bolt://example:9999",
        auth=(args.username, args.password),
    )
    load_repo_mock.assert_called_once_with(
        args.repo_url, driver_instance, args.database
    )
    driver_instance.verify_connectivity.assert_called_once()
    driver_instance.close.assert_called_once()
