"""WP4 targeted footprint-reconcile assertions (live).

These are narrower than the equivalence suite: they pin the specific behaviours
the reconcile must guarantee.
  * incoming CALLS to a SURVIVING method are preserved (reconcile, not raze),
  * incoming CALLS to a DELETED method are removed,
  * orphaned :Import nodes are garbage-collected,
  * a deleted file keeps its :File node (git anchor) and is flagged.
"""

from __future__ import annotations

import os

import pytest

from tests.integration.incremental_common import (
    commit_all,
    full_ingest,
    incremental_ingest,
    init_repo,
    remove,
    wipe,
    write,
)

pytestmark = pytest.mark.live

_A = """package pkg;
import java.util.List;
public class A {
    public int stable() { return 1; }
    public int victim() { return 9; }
}
"""

_B = """package pkg;
public class B {
    public int callsStable() { A a = new A(); return a.stable(); }
    public int callsVictim() { A a = new A(); return a.victim(); }
}
"""

# HEAD version of A: victim() removed and the (unused) List import dropped.
_A_HEAD = """package pkg;
public class A {
    public int stable() { return 1; }
}
"""


def _database() -> str:
    return os.getenv("NEO4J_DATABASE", "neo4j")


def _count(session, cypher: str) -> int:
    rec = session.run(cypher).single()
    return int(rec["c"]) if rec else 0


def test_footprint_reconcile_preserves_and_prunes(neo4j_driver, tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    write(repo, "pkg/A.java", _A)
    write(repo, "pkg/B.java", _B)
    base = commit_all(repo, "base")

    database = _database()
    with neo4j_driver.session(database=database) as s:
        wipe(s)
    full_ingest(neo4j_driver, database, repo)

    # Sanity at BASE: both cross-file CALLS and the List Import exist.
    with neo4j_driver.session(database=database) as s:
        assert (
            _count(
                s,
                "MATCH (:Method {name:'callsStable'})-[:CALLS]->(:Method {name:'stable'}) "
                "RETURN count(*) AS c",
            )
            == 1
        )
        assert (
            _count(
                s,
                "MATCH (:Method {name:'callsVictim'})-[:CALLS]->(:Method {name:'victim'}) "
                "RETURN count(*) AS c",
            )
            == 1
        )
        assert _count(s, "MATCH (:Import {import_path:'java.util.List'}) RETURN count(*) AS c") == 1

    # HEAD: A loses victim() and the List import; B is untouched.
    write(repo, "pkg/A.java", _A_HEAD)
    commit_all(repo, "remove victim + import")
    incremental_ingest(neo4j_driver, database, repo, base)

    with neo4j_driver.session(database=database) as s:
        # Surviving method keeps its incoming cross-file CALLS (reconcile, not raze).
        assert (
            _count(
                s,
                "MATCH (:Method {name:'callsStable'})-[:CALLS]->(:Method {name:'stable'}) "
                "RETURN count(*) AS c",
            )
            == 1
        ), "incoming CALLS to a surviving method must be preserved"

        # Deleted method and its incoming CALLS are gone.
        assert _count(s, "MATCH (m:Method {name:'victim'}) RETURN count(m) AS c") == 0
        assert (
            _count(
                s,
                "MATCH (:Method {name:'callsVictim'})-[:CALLS]->(:Method) RETURN count(*) AS c",
            )
            == 0
        ), "incoming CALLS to a deleted method must be removed"

        # Orphaned Import node is garbage-collected.
        assert (
            _count(s, "MATCH (:Import {import_path:'java.util.List'}) RETURN count(*) AS c") == 0
        ), "orphaned Import must be GC'd"


def test_deleted_file_node_retained_and_flagged(neo4j_driver, tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    write(repo, "pkg/A.java", _A)
    write(repo, "pkg/B.java", _B)
    base = commit_all(repo, "base")

    database = _database()
    with neo4j_driver.session(database=database) as s:
        wipe(s)
    full_ingest(neo4j_driver, database, repo)

    # Delete B.java at HEAD.
    remove(repo, "pkg/B.java")
    commit_all(repo, "delete B")
    incremental_ingest(neo4j_driver, database, repo, base)

    with neo4j_driver.session(database=database) as s:
        # File node retained (anchors git history) and flagged deleted_at_head.
        rec = s.run(
            "MATCH (f:File {path:'pkg/B.java'}) "
            "RETURN f.deleted_at_head AS flag, f.method_count AS mc"
        ).single()
        assert rec is not None, "deleted file's :File node must be retained for history"
        assert rec["flag"] is True, "deleted file must be flagged deleted_at_head"
        assert rec["mc"] is None, "structure props must be cleared on a deleted file"

        # Its structural footprint (class + methods) is gone.
        assert _count(s, "MATCH (c:Class {file:'pkg/B.java'}) RETURN count(c) AS c") == 0
        assert _count(s, "MATCH (m:Method {file:'pkg/B.java'}) RETURN count(m) AS c") == 0

        # Its git history anchor still resolves (FileVer -> File).
        assert (
            _count(
                s,
                "MATCH (:FileVer {path:'pkg/B.java'})-[:OF_FILE]->(:File {path:'pkg/B.java'}) "
                "RETURN count(*) AS c",
            )
            >= 1
        )
