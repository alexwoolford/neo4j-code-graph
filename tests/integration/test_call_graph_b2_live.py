"""Live regression for B2 call-graph soundness:
- Method.arity is persisted.
- CALLS link query disambiguates overloads by argc <-> arity (C1).

Pre-B2 behavior: a single call site with N args linked to ALL same-name
overloads in the receiver class regardless of arity. With arity-aware MERGE,
one-arg calls only link to one-arg overloads, etc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def _get_driver_or_skip():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")
    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


# Three "parse" overloads (1, 2, and 2 args) with same-class callers: this
# is the in-class case the arity filter solves. Pre-B2: every callsite fans
# out to all 3 overloads regardless of arity. Post-B2: callOne hits only the
# 1-arg overload; callTwo hits the two 2-arg overloads (they share arity, so
# arity alone isn't enough to disambiguate -- that's the residual).
# Expected: 1 (from callOne) + 2 (from callTwo to the two 2-arg overloads) = 3.
JAVA_FIXTURE = """
package demo;

class Parser {
    String parse(String s) { return s; }
    String parse(String s, String t) { return s + t; }
    String parse(String s, Integer n) { return s + n; }

    void callOne() {
        parse("a");
    }
    void callTwo() {
        parse("a", "b");
    }
}
"""


def _ingest(session, repo: Path) -> None:
    from src.analysis.code_analysis import (
        bulk_create_nodes_and_relationships,
        extract_file_data,
    )
    from src.data.schema_management import setup_complete_schema

    setup_complete_schema(session)
    session.run("MATCH (n) DETACH DELETE n").consume()
    setup_complete_schema(session)

    files_data = []
    for p in repo.rglob("*.java"):
        fd = extract_file_data(p, repo)
        if fd:
            files_data.append(fd)
    bulk_create_nodes_and_relationships(
        session,
        files_data,
        file_embeddings=[],
        method_embeddings=[],
    )


def test_arity_aware_calls_disambiguate_overloads(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    src = repo / "src" / "main" / "java" / "demo"
    src.mkdir(parents=True, exist_ok=True)
    (src / "Parser.java").write_text(JAVA_FIXTURE, encoding="utf-8")

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            _ingest(s, repo)

            # Method.arity is persisted on every Method node
            r = s.run("MATCH (m:Method) WHERE m.arity IS NULL RETURN count(m) AS c").single()
            assert r["c"] == 0, f"{r['c']} methods missing arity property"

            # Each Parser.parse overload exists with the right arity
            arities = sorted(
                row["a"]
                for row in s.run(
                    "MATCH (m:Method {name: 'parse', class_name: 'Parser'}) " "RETURN m.arity AS a"
                ).data()
            )
            assert arities == [1, 2, 2], arities

            # callOne() makes ONE 1-arg call -> exactly 1 CALLS edge to the 1-arg overload.
            # Pre-B2: 3 (one per overload, fan-out).
            r = s.run(
                """
                MATCH (caller:Method {name: 'callOne'})-[:CALLS]->(callee:Method
                    {name: 'parse', class_name: 'Parser'})
                RETURN callee.arity AS a, count(*) AS c
                ORDER BY a
                """
            ).data()
            assert r == [{"a": 1, "c": 1}], (
                f"callOne should link to exactly 1 (the 1-arg overload), got {r}; "
                "pre-B2 fan-out would have produced 3 edges (1 per overload)"
            )

            # callTwo() makes ONE 2-arg call. Arity narrows to the two 2-arg overloads
            # (residual: arity alone can't pick between parse(String,String) and
            # parse(String,Integer); needs argument-type analysis). Expected: 2 edges.
            # Pre-B2: 3 (full fan-out).
            r = s.run(
                """
                MATCH (caller:Method {name: 'callTwo'})-[:CALLS]->(callee:Method
                    {name: 'parse', class_name: 'Parser'})
                RETURN callee.arity AS a, count(*) AS c
                ORDER BY a
                """
            ).data()
            assert r == [{"a": 2, "c": 2}], (
                f"callTwo should link to the two 2-arg overloads, got {r}; "
                "pre-B2 fan-out would have produced 3 edges (1 per overload)"
            )

            # Total: 1 + 2 = 3 CALLS edges. Pre-B2 baseline: 6.
            r = s.run(
                """
                MATCH (caller:Method)-[:CALLS]->(callee:Method
                    {name: 'parse', class_name: 'Parser'})
                RETURN count(*) AS c
                """
            ).single()
            assert r["c"] == 3, (
                f"expected 3 total CALLS edges (arity-aware), got {r['c']}; "
                "pre-B2 fan-out would have produced 6 (2 callers x 3 overloads)"
            )
