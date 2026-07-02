"""Fast unit tests for WP4 delta detection (real tmp git repo, no Neo4j)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.analysis.delta import (
    changed_and_deleted,
    classify_ingest_mode,
    diff_changed_files,
    get_head_sha,
    is_ancestor,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "d@e.com")
    _git(repo, "config", "user.name", "D")
    _git(repo, "config", "commit.gpgsign", "false")


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _commit(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def test_diff_changed_files_buckets_java_only(tmp_path):
    repo = tmp_path / "r"
    _init(repo)
    _write(repo, "Foo.java", "class Foo {}\n")
    _write(repo, "Bar.java", "class Bar {}\n")
    _write(repo, "Keep.java", "class Keep { int a; }\n")
    _write(repo, "notes.txt", "hello\n")
    base = _commit(repo, "base")

    # Modify Keep, rename Foo->Foo2 (content preserved => rename), delete Bar,
    # add New.java, touch a non-Java file (must be ignored).
    _write(repo, "Keep.java", "class Keep { int a; int b; }\n")
    _git(repo, "mv", "Foo.java", "Foo2.java")
    _git(repo, "rm", "-q", "Bar.java")
    _write(repo, "New.java", "class New {}\n")
    _write(repo, "notes.txt", "changed\n")
    head = _commit(repo, "head")

    delta = diff_changed_files(repo, base, head)
    assert delta["added"] == ["New.java"]
    assert delta["modified"] == ["Keep.java"]
    assert delta["deleted"] == ["Bar.java"]
    assert delta["renamed"] == [("Foo.java", "Foo2.java")]

    to_extract, removed = changed_and_deleted(delta)
    assert sorted(to_extract) == ["Foo2.java", "Keep.java", "New.java"]
    assert sorted(removed) == ["Bar.java", "Foo.java"]


def test_get_head_sha_and_is_ancestor(tmp_path):
    repo = tmp_path / "r"
    _init(repo)
    _write(repo, "A.java", "class A {}\n")
    base = _commit(repo, "base")
    _write(repo, "A.java", "class A { int x; }\n")
    head = _commit(repo, "head")

    assert get_head_sha(repo) == head
    assert is_ancestor(repo, base, head) is True
    assert is_ancestor(repo, head, base) is False


def test_get_head_sha_none_for_non_repo(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert get_head_sha(d) is None


def test_classify_ingest_mode_full_triggers():
    # Force full always wins.
    assert classify_ingest_mode(
        force_full=True,
        has_hwm=True,
        branch_changed=False,
        schema_changed=False,
        is_ancestor=True,
        is_shallow=False,
    ) == ("full", "forced full re-ingest (--full)")

    # No HWM -> full.
    mode, reason = classify_ingest_mode(
        force_full=False,
        has_hwm=False,
        branch_changed=False,
        schema_changed=False,
        is_ancestor=True,
        is_shallow=False,
    )
    assert mode == "full" and "no prior successful ingest" in reason

    # Each independent trigger forces full.
    for kwargs, needle in [
        (dict(branch_changed=True), "branch changed"),
        (dict(schema_changed=True), "SCHEMA_VERSION changed"),
        (dict(is_shallow=True), "shallow clone"),
        (dict(is_ancestor=False), "not an ancestor"),
    ]:
        base = dict(
            force_full=False,
            has_hwm=True,
            branch_changed=False,
            schema_changed=False,
            is_ancestor=True,
            is_shallow=False,
        )
        base.update(kwargs)
        mode, reason = classify_ingest_mode(**base)
        assert mode == "full" and needle in reason


def test_classify_ingest_mode_incremental_happy_path():
    mode, reason = classify_ingest_mode(
        force_full=False,
        has_hwm=True,
        branch_changed=False,
        schema_changed=False,
        is_ancestor=True,
        is_shallow=False,
    )
    assert mode == "incremental" and "HEAD-delta" in reason
