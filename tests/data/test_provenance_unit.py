"""Fast unit tests for provenance helpers (no Neo4j)."""

from __future__ import annotations

from src.data.provenance import normalize_repo_url, tool_version


def test_normalize_strips_git_suffix_and_trailing_slash():
    assert normalize_repo_url("https://github.com/x/y.git") == "https://github.com/x/y"
    assert normalize_repo_url("https://github.com/x/y/") == "https://github.com/x/y"
    assert normalize_repo_url("git@github.com:x/y.git") == "git@github.com:x/y"


def test_normalize_local_dir_without_origin_returns_abspath(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    assert normalize_repo_url(str(d)) == str(d.resolve())


def test_normalize_empty_is_empty():
    assert normalize_repo_url("") == ""


def test_tool_version_is_nonempty_string():
    v = tool_version()
    assert isinstance(v, str) and v
