#!/usr/bin/env python3
"""Live end-to-end smoke test for the curated code-graph MCP server.

Seeds a miniature but shape-accurate graph on the session testcontainer (whose
NEO4J_* env the conftest autouse fixture exports), spawns
``python -m mcp_server.server`` over stdio, and drives it with a real MCP
client: lists all eight tools and calls a representative subset, validating the
response envelope and the seeded rows.

Runs under the repo's coroutine test runner in ``tests/conftest.py`` (no
pytest-asyncio needed).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import pytest

pytestmark = pytest.mark.live

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:  # pragma: no cover - mcp always installed in the dev env
    pytest.skip("mcp client not available", allow_module_level=True)


# Seed identifiers reused across assertions.
CVE_REACHABLE = "CVE-2024-0001"
CVE_NOT_IMPORTED = "CVE-2024-9999"
GAV_VULN = "org.example:vuln-lib:1.0.0"
CONTROLLER = "src/main/java/com/acme/Controller.java"
SERVICE = "src/main/java/com/acme/Service.java"
ENTRY_SIG = "com.acme.Controller#handle():void"
FRONTIER_SIG = "com.acme.Controller#callVuln():void"


def _seed(session) -> None:
    """Write the minimal graph the smoke test asserts against."""
    session.run("MATCH (n) DETACH DELETE n").consume()

    # CVE 1: full reachable chain.
    session.run(
        """
        MERGE (dep:ExternalDependency {group_id: 'org.example', artifact_id: 'vuln-lib',
                                       version: '1.0.0'})
        SET dep.package = 'org.example.vuln'
        MERGE (cve:CVE {id: $cve}) SET cve.cvss_score = 9.8, cve.severity = 'CRITICAL'
        MERGE (cve)-[:AFFECTS {confidence: 0.95, match_type: 'precise_gav'}]->(dep)
        MERGE (imp:Import {import_path: 'org.example.vuln.Api'}) SET imp.import_type = 'external'
        MERGE (imp)-[:DEPENDS_ON]->(dep)
        MERGE (f:File {path: $controller}) SET f.change_count = 5
        MERGE (f)-[:IMPORTS]->(imp)
        """,
        cve=CVE_REACHABLE,
        controller=CONTROLLER,
    ).consume()

    # Methods: entry (annotated) -> frontier (CALLS_EXTERNAL). PageRank set.
    session.run(
        """
        UNWIND $methods AS m
        MERGE (mm:Method {method_signature: m.sig})
        SET mm.id = m.sig, mm.name = m.name, mm.file = m.file, mm.line = m.line,
            mm.is_public = m.is_public, mm.is_static = m.is_static,
            mm.is_test_method = false, mm.pagerank_score = m.pr
        WITH mm, m
        MATCH (f:File {path: m.file})
        MERGE (f)-[:DECLARES]->(mm)
        """,
        methods=[
            {
                "sig": ENTRY_SIG,
                "name": "handle",
                "file": CONTROLLER,
                "line": 10,
                "is_public": True,
                "is_static": False,
                "pr": 0.9,
            },
            {
                "sig": FRONTIER_SIG,
                "name": "callVuln",
                "file": CONTROLLER,
                "line": 20,
                "is_public": True,
                "is_static": False,
                "pr": 0.5,
            },
        ],
    ).consume()

    session.run(
        """
        MERGE (a:Annotation {name: 'GetMapping'})
        WITH a
        MATCH (entry:Method {method_signature: $entry})
        MERGE (entry)-[:ANNOTATED]->(a)
        WITH entry
        MATCH (frontier:Method {method_signature: $frontier})
        MERGE (entry)-[:CALLS]->(frontier)
        WITH frontier
        MATCH (imp:Import {import_path: 'org.example.vuln.Api'})
        MERGE (frontier)-[:CALLS_EXTERNAL {method_name: 'exec', target_class: 'Api',
                                           confidence: 'HIGH', confidence_rank: 3}]->(imp)
        """,
        entry=ENTRY_SIG,
        frontier=FRONTIER_SIG,
    ).consume()

    # CVE 2: dependency has no inbound DEPENDS_ON -> NOT_IMPORTED.
    session.run(
        """
        MERGE (dep:ExternalDependency {group_id: 'org.other', artifact_id: 'orphan-lib',
                                       version: '2.0.0'})
        MERGE (cve:CVE {id: $cve}) SET cve.cvss_score = 7.5, cve.severity = 'HIGH'
        MERGE (cve)-[:AFFECTS {confidence: 0.9, match_type: 'precise_gav'}]->(dep)
        """,
        cve=CVE_NOT_IMPORTED,
    ).consume()

    # Git history: one developer, two commits touching both files.
    session.run(
        """
        MERGE (dev:Developer {email: 'dev@example.com'}) SET dev.name = 'Dev One'
        MERGE (fc:File {path: $controller})
        MERGE (fs:File {path: $service}) SET fs.change_count = 3
        WITH dev, fc, fs
        UNWIND $commits AS cm
        MERGE (c:Commit {sha: cm.sha}) SET c.date = datetime(cm.date)
        MERGE (dev)-[:AUTHORED]->(c)
        MERGE (fvc:FileVer {sha: cm.sha, path: $controller})
        MERGE (c)-[:CHANGED]->(fvc) MERGE (fvc)-[:OF_FILE]->(fc)
        MERGE (fvs:FileVer {sha: cm.sha, path: $service})
        MERGE (c)-[:CHANGED]->(fvs) MERGE (fvs)-[:OF_FILE]->(fs)
        """,
        controller=CONTROLLER,
        service=SERVICE,
        commits=[
            {"sha": "s1", "date": "2024-01-10T09:00:00Z"},
            {"sha": "s2", "date": "2024-03-05T09:00:00Z"},
        ],
    ).consume()

    # CO_CHANGED partner (canonical direction: Controller.java < Service.java).
    session.run(
        """
        MATCH (fc:File {path: $controller}), (fs:File {path: $service})
        MERGE (fc)-[cc:CO_CHANGED]->(fs) SET cc.support = 6, cc.confidence = 0.7
        """,
        controller=CONTROLLER,
        service=SERVICE,
    ).consume()


def _envelope(result: Any) -> dict[str, Any]:
    """Extract and JSON-decode the response envelope from a CallToolResult."""
    assert getattr(result, "isError", False) is False, f"tool call errored: {result}"
    content = result.content
    assert content, "tool returned no content"
    text = content[0].text
    return json.loads(text)


def _assert_envelope(env: dict[str, Any], tool: str) -> None:
    assert env["schema_version"] == "1.0"
    assert env["tool"] == tool
    assert env["row_count"] == len(env["rows"])
    assert env["caveats"], "caveats must be present"
    assert any("Java" in c for c in env["caveats"])
    assert any("ranked triage, not proof" in c for c in env["caveats"])


async def test_stdio_smoke(neo4j_driver):
    db = os.getenv("NEO4J_DATABASE", "neo4j")
    with neo4j_driver.session(database=db) as session:
        _seed(session)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env=os.environ.copy(),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            tools = listed.tools
            names = {t.name for t in tools}
            expected = {
                "cve_reachability",
                "blast_radius",
                "hotspots",
                "ownership",
                "risk_register",
                "dependency_cves",
                "unreachable_cves",
                "graph_summary",
            }
            assert names == expected, f"unexpected tool set: {names}"
            for tool in tools:
                assert "Java" in (tool.description or ""), f"{tool.name} missing scope sentence"

            # cve_reachability: the seeded chain is reachable at hop 1.
            env = _envelope(await session.call_tool("cve_reachability", {"cve_id": CVE_REACHABLE}))
            _assert_envelope(env, "cve_reachability")
            assert env["row_count"] >= 1
            row = env["rows"][0]
            assert row["frontier_method"] == FRONTIER_SIG
            assert row["cve_id"] == CVE_REACHABLE
            assert row["min_hops"] == 1

            # risk_register: both seeded CVEs at CVSS >= 7.0.
            env = _envelope(await session.call_tool("risk_register", {"min_cvss": 7.0}))
            _assert_envelope(env, "risk_register")
            statuses = {r["cve_id"]: r["status"] for r in env["rows"]}
            assert statuses.get(CVE_REACHABLE) == "REACHABLE"
            assert statuses.get(CVE_NOT_IMPORTED) == "NOT_IMPORTED"

            # unreachable_cves: the orphan CVE with dismissal evidence.
            env = _envelope(await session.call_tool("unreachable_cves", {"min_cvss": 0.0}))
            _assert_envelope(env, "unreachable_cves")
            unreachable = {r["cve_id"]: r for r in env["rows"]}
            assert CVE_NOT_IMPORTED in unreachable
            assert unreachable[CVE_NOT_IMPORTED]["status"] == "NOT_IMPORTED"
            assert unreachable[CVE_NOT_IMPORTED]["evidence"]
            assert CVE_REACHABLE not in unreachable

            # graph_summary: analytics flags reflect the seeded graph.
            env = _envelope(await session.call_tool("graph_summary", {}))
            _assert_envelope(env, "graph_summary")
            summary_row = env["rows"][0]
            assert summary_row["node_counts"]["CVE"] >= 2
            assert summary_row["has_pagerank_score"] is True
            assert summary_row["has_co_changed"] is True
            assert summary_row["latest_commit_date"] is not None

            # dependency_cves: direct GAV lookup finds the reachable CVE.
            env = _envelope(await session.call_tool("dependency_cves", {"gav": GAV_VULN}))
            _assert_envelope(env, "dependency_cves")
            assert any(r["cve_id"] == CVE_REACHABLE for r in env["rows"])

            # blast_radius: the co-changed partner shows up (support 6 >= 5).
            env = _envelope(await session.call_tool("blast_radius", {"file_path": CONTROLLER}))
            _assert_envelope(env, "blast_radius")
            blast = env["rows"][0]
            partners = {p["path"] for p in blast["co_changed_files"]}
            assert SERVICE in partners

            # hotspots + ownership: exercise the remaining tools end-to-end.
            env = _envelope(await session.call_tool("hotspots", {"days": 3650, "top_n": 10}))
            _assert_envelope(env, "hotspots")
            hot_paths = {r["path"] for r in env["rows"]}
            assert CONTROLLER in hot_paths

            env = _envelope(
                await session.call_tool("ownership", {"path_or_package": "src/main/java/com/acme"})
            )
            _assert_envelope(env, "ownership")
            assert any(r["developer_email"] == "dev@example.com" for r in env["rows"])
