"""WP4 correctness invariant: incremental(BASE->HEAD) == full-ingest(HEAD).

For each scenario we ingest the SAME programmatic git repo two ways into the
same (wiped) database and assert the canonical graph snapshots are identical:

  * FULL:        wipe -> full ingest of HEAD
  * INCREMENTAL: wipe -> full ingest of BASE -> incremental patch BASE..HEAD

:func:`snapshot_graph` keys nodes by natural key and relationships by
(type, src-key, dst-key), excluding analytics scores, Louvain community ids,
CO_CHANGED, and Ingest/Repository provenance (see module docstring there).
"""

from __future__ import annotations

import os

import pytest

from tests.integration.incremental_common import (
    build_base_repo,
    checkout,
    diff_snapshots,
    full_ingest,
    git,
    incremental_ingest,
    mutate_add_method,
    mutate_change_imports,
    mutate_delete_file,
    mutate_delete_method,
    mutate_modify_body,
    snapshot_graph,
    wipe,
)

pytestmark = pytest.mark.live


def _database() -> str:
    return os.getenv("NEO4J_DATABASE", "neo4j")


def _assert_equivalent(neo4j_driver, repo, base_sha: str) -> None:
    database = _database()
    head_sha = git(repo, "rev-parse", "HEAD")
    assert head_sha != base_sha, "scenario must advance HEAD"

    # Path 1 — full ingest of HEAD.
    with neo4j_driver.session(database=database) as s:
        wipe(s)
    full_ingest(neo4j_driver, database, repo)
    with neo4j_driver.session(database=database) as s:
        snap_full = snapshot_graph(s)

    # Path 2 — full ingest of BASE, then incremental patch to HEAD.
    checkout(repo, base_sha)
    with neo4j_driver.session(database=database) as s:
        wipe(s)
    full_ingest(neo4j_driver, database, repo)
    checkout(repo, head_sha)
    changed, deleted = incremental_ingest(neo4j_driver, database, repo, base_sha)
    with neo4j_driver.session(database=database) as s:
        snap_incr = snapshot_graph(s)

    # Sanity: the delta was non-empty (the test actually exercised the patch).
    assert changed or deleted, "expected a non-empty delta for this scenario"

    assert snap_full == snap_incr, "\n" + diff_snapshots(snap_full, snap_incr)


def test_equivalence_modify_method_body(neo4j_driver, tmp_path):
    repo = tmp_path / "repo"
    base = build_base_repo(repo)
    mutate_modify_body(repo)
    _assert_equivalent(neo4j_driver, repo, base)


def test_equivalence_add_method(neo4j_driver, tmp_path):
    repo = tmp_path / "repo"
    base = build_base_repo(repo)
    mutate_add_method(repo)
    _assert_equivalent(neo4j_driver, repo, base)


def test_equivalence_delete_method(neo4j_driver, tmp_path):
    repo = tmp_path / "repo"
    base = build_base_repo(repo)
    mutate_delete_method(repo)
    _assert_equivalent(neo4j_driver, repo, base)

    # Targeted: the deleted method and its CALLS must be gone in incremental.
    with neo4j_driver.session(database=_database()) as s:
        rec = s.run("MATCH (m:Method) WHERE m.name = 'alpha' RETURN count(m) AS c").single()
        assert rec["c"] == 0


def test_equivalence_delete_file(neo4j_driver, tmp_path):
    repo = tmp_path / "repo"
    base = build_base_repo(repo)
    mutate_delete_file(repo)
    _assert_equivalent(neo4j_driver, repo, base)


def test_equivalence_change_imports(neo4j_driver, tmp_path):
    repo = tmp_path / "repo"
    base = build_base_repo(repo)
    mutate_change_imports(repo)
    _assert_equivalent(neo4j_driver, repo, base)
