import os
import sys
import types
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Stub heavy modules
sys.modules.setdefault("git", types.SimpleNamespace(Repo=MagicMock()))
sys.modules.setdefault("neo4j", types.SimpleNamespace(GraphDatabase=MagicMock()))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda **k: None))

import git_history


def _make_commit(sha, name, email, files):
    return types.SimpleNamespace(
        hexsha=sha,
        message=f"msg {sha}",
        author=types.SimpleNamespace(name=name, email=email),
        files=files,
    )


def test_load_history_runs_expected_queries():
    repo_mock = MagicMock()
    repo_mock.iter_commits.return_value = [
        _make_commit("a1", "Alice", "a@example.com", ["foo.java"]),
        _make_commit("b2", "Bob", "b@example.com", ["foo.java", "bar.java"]),
    ]
    git_history.Repo.return_value = repo_mock

    session_mock = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = session_mock
    driver_mock = MagicMock()
    driver_mock.session.return_value = session_cm

    git_history.load_history("repo", driver_mock)

    queries = [c.args[0] for c in session_mock.run.call_args_list]
    assert any("Developer" in q for q in queries)
    assert any("Commit" in q for q in queries)
    assert any("FileVer" in q for q in queries)
    assert any("AUTHORED" in q for q in queries)
    assert any("CHANGED" in q for q in queries)
