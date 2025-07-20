import os
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import git_history_to_graph


class DummyCommit:
    def __init__(self, sha, email, files):
        self.hexsha = sha
        self.committed_datetime = datetime(2024, 1, 1)
        self.message = "msg"
        self.author = types.SimpleNamespace(email=email)
        self.stats = types.SimpleNamespace(files=files)


def test_load_history_executes_cypher(tmp_path):
    commit = DummyCommit("abc", "a@b.com", {"file.java": {"lines": 10}})
    repo_mock = MagicMock()
    repo_mock.iter_commits.return_value = [commit]
    repo_mock.git.checkout.return_value = None

    session_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session_mock
    driver_mock = MagicMock()
    driver_mock.session.return_value = session_cm

    with patch.object(git_history_to_graph.Repo, "clone_from", return_value=repo_mock):
        git_history_to_graph.load_history("url", "main", driver_mock)

    queries = [c.args[0] for c in session_mock.run.call_args_list]
    assert any("MERGE (c:Commit" in q for q in queries)
    assert any("MERGE (d:Developer" in q for q in queries)
    assert any("MERGE (fv:FileVer" in q for q in queries)


def test_main_accepts_optional_arguments(monkeypatch):
    args = types.SimpleNamespace(
        repo_url="https://example.com/repo.git",
        branch="main",
        uri="bolt://example",
        username="neo4j",
        password="secret",
        database="testdb",
        log_level="INFO",
        log_file=None,
    )

    driver_instance = MagicMock()
    monkeypatch.setattr(git_history_to_graph, "parse_args", lambda: args)
    ensure_port_mock = MagicMock(return_value="bolt://example:9999")
    monkeypatch.setattr(git_history_to_graph, "ensure_port", ensure_port_mock)
    monkeypatch.setattr(
        git_history_to_graph.GraphDatabase,
        "driver",
        MagicMock(return_value=driver_instance),
    )
    load_history_mock = MagicMock()
    monkeypatch.setattr(git_history_to_graph, "load_history", load_history_mock)

    git_history_to_graph.main()

    assert ensure_port_mock.call_count == 2
    ensure_port_mock.assert_has_calls([call(args.uri), call(args.uri)])
    git_history_to_graph.GraphDatabase.driver.assert_called_once_with(
        "bolt://example:9999",
        auth=(args.username, args.password),
    )
    load_history_mock.assert_called_once_with(
        args.repo_url, args.branch, driver_instance, args.database
    )
    driver_instance.verify_connectivity.assert_called_once()
    driver_instance.close.assert_called_once()
