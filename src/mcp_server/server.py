#!/usr/bin/env python3
"""FastMCP stdio server exposing curated code-graph risk queries as typed tools.

Eight thin wrappers over ``src/security/reachability.py`` (the single source of
truth for Cypher — this module contains none). Each tool validates its
arguments, opens a *read-only* Neo4j session, calls one reachability function,
and returns a versioned response envelope (see :mod:`mcp_server.contracts`).

Connection settings come from :func:`utils.neo4j_utils.get_neo4j_config`
(``NEO4J_URI/USERNAME/PASSWORD/DATABASE``). The driver is a lazy singleton
created on the first tool call, so ``import`` and ``--help`` work offline. An
optional ``CODEGRAPH_MCP_NAMESPACE`` env var prefixes every tool name so this
server can coexist with other MCP servers in one client config.

Run with ``code-graph-mcp`` (entry point) or ``python -m mcp_server.server``.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

import neo4j
from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase

try:  # top-level package names (src on sys.path via the editable install)
    from constants import DEFAULT_MAX_HOPS  # type: ignore
    from mcp_server.contracts import (  # type: ignore
        SCOPE_SENTENCE,
        build_envelope,
        namespaced_tool_name,
        parse_gav,
        validate_max_hops,
    )
    from security import reachability  # type: ignore
    from utils.neo4j_utils import get_neo4j_config  # type: ignore
except Exception:  # pragma: no cover - source-tree execution path
    from src.constants import DEFAULT_MAX_HOPS  # type: ignore
    from src.mcp_server.contracts import (  # type: ignore
        SCOPE_SENTENCE,
        build_envelope,
        namespaced_tool_name,
        parse_gav,
        validate_max_hops,
    )
    from src.security import reachability  # type: ignore
    from src.utils.neo4j_utils import get_neo4j_config  # type: ignore

NAMESPACE_ENV = "CODEGRAPH_MCP_NAMESPACE"

# CVE statuses (from reachability.triage_summary) that mean "no reachable call
# path" — the dismissal set surfaced by unreachable_cves.
_UNREACHABLE_STATUSES = {
    reachability.STATUS_NOT_IMPORTED,
    reachability.STATUS_NO_FRONTIER,
    reachability.STATUS_FRONTIER_UNREACHABLE,
}

# --- Lazy read-only connection ----------------------------------------------

_DRIVER: neo4j.Driver | None = None
_DATABASE: str | None = None


def _get_driver() -> neo4j.Driver:
    """Return the process-wide driver, creating it on first use (lazy)."""
    global _DRIVER, _DATABASE
    if _DRIVER is None:
        uri, username, password, database = get_neo4j_config()
        _DRIVER = GraphDatabase.driver(uri, auth=(username, password))
        _DATABASE = database
    return _DRIVER


@contextlib.contextmanager
def _read_session() -> Iterator[neo4j.Session]:
    """Open a READ-only session against the configured database."""
    driver = _get_driver()
    session = driver.session(database=_DATABASE, default_access_mode=neo4j.READ_ACCESS)
    try:
        yield session
    finally:
        session.close()


def _require_nonempty(value: Any, name: str) -> str:
    """Validate a required non-empty string argument."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _unreachable_evidence(status: str, max_hops: int) -> str:
    """Human-readable reason a CVE has no reachable call path."""
    if status == reachability.STATUS_NOT_IMPORTED:
        return "No File imports a dependency this CVE affects — not on the compile/runtime path."
    if status == reachability.STATUS_NO_FRONTIER:
        return (
            "Dependency is imported but no method calls into it "
            "(no CALLS_EXTERNAL evidence at the confidence threshold)."
        )
    return f"Frontier methods exist but no entry point reaches them within {max_hops} hop(s)."


# --- Tools (thin wrappers; ZERO Cypher lives here) ---------------------------


def cve_reachability(
    cve_id: str, max_hops: int = DEFAULT_MAX_HOPS, include_tests: bool = False
) -> dict[str, Any]:
    """Which Java methods can reach a CVE's vulnerable dependency, and how."""
    cve = _require_nonempty(cve_id, "cve_id")
    hops = validate_max_hops(max_hops)
    with _read_session() as session:
        rows = reachability.reachability_for_cve(
            session, cve, max_hops=hops, include_tests=bool(include_tests)
        )
    summary = f"{len(rows)} reachable frontier method(s) for {cve} within {hops} hop(s)."
    return build_envelope("cve_reachability", summary, rows)


def blast_radius(file_path: str, min_support: int = 5) -> dict[str, Any]:
    """Change-coupling blast radius and ownership for one file."""
    path = _require_nonempty(file_path, "file_path")
    result = None
    with _read_session() as session:
        result = reachability.blast_radius_ownership(session, path, min_support=int(min_support))
    summary = (
        f"{result['co_change_count']} co-changed file(s) and "
        f"{len(result['ownership']['top_committers'])} committer(s) for {path}."
    )
    return build_envelope("blast_radius", summary, [result])


def hotspots(days: int = 90, top_n: int = 20) -> dict[str, Any]:
    """Files that change most often, joined with their peak method PageRank."""
    top = int(top_n)
    if top < 1:
        raise ValueError("top_n must be >= 1")
    with _read_session() as session:
        rows = reachability.hotspots(session, days=int(days), top_n=top)
    summary = f"{len(rows)} change hotspot(s) over the last {days} day(s)."
    return build_envelope("hotspots", summary, rows, truncated=len(rows) >= top)


def ownership(path_or_package: str, days: int | None = None) -> dict[str, Any]:
    """Who owns the code under a path or package (commits, files, share)."""
    prefix = _require_nonempty(path_or_package, "path_or_package")
    window = None if days is None else int(days)
    with _read_session() as session:
        rows = reachability.ownership(session, prefix, days=window)
    scope = "all history" if window is None else f"the last {window} day(s)"
    summary = f"{len(rows)} contributor(s) under '{prefix}' over {scope}."
    return build_envelope("ownership", summary, rows)


def risk_register(
    min_cvss: float = 7.0, max_hops: int = DEFAULT_MAX_HOPS, limit: int = 25
) -> dict[str, Any]:
    """The ranked CVE risk register: every AFFECTS-linked CVE with its status."""
    hops = validate_max_hops(max_hops)
    cap = int(limit)
    if cap < 1:
        raise ValueError("limit must be >= 1")
    with _read_session() as session:
        triage = reachability.triage_summary(session, risk_threshold=float(min_cvss), max_hops=hops)
    cves = triage["cves"]
    summ = triage["summary"]
    rows = cves[:cap]
    summary = (
        f"{summ['total']} CVE(s) at CVSS >= {min_cvss}: {summ['reachable']} reachable, "
        f"{summ['triage_reduction_pct']}% triage reduction."
    )
    return build_envelope("risk_register", summary, rows, truncated=len(cves) > cap)


def dependency_cves(gav: str) -> dict[str, Any]:
    """Which CVEs affect an exact Maven coordinate (group:artifact:version)."""
    group_id, artifact_id, version = parse_gav(gav)
    with _read_session() as session:
        rows = reachability.dependency_cves(session, group_id, artifact_id, version)
    summary = f"{len(rows)} CVE(s) affecting {group_id}:{artifact_id}:{version}."
    return build_envelope("dependency_cves", summary, rows)


def unreachable_cves(min_cvss: float = 0.0, max_hops: int = DEFAULT_MAX_HOPS) -> dict[str, Any]:
    """CVEs with no reachable call path — dismissal evidence for triage."""
    hops = validate_max_hops(max_hops)
    with _read_session() as session:
        triage = reachability.triage_summary(session, risk_threshold=float(min_cvss), max_hops=hops)
    rows: list[dict[str, Any]] = []
    for cve_row in triage["cves"]:
        status = cve_row["status"]
        if status in _UNREACHABLE_STATUSES:
            row = dict(cve_row)
            row["evidence"] = _unreachable_evidence(status, hops)
            rows.append(row)
    summary = f"{len(rows)} CVE(s) with no reachable call path at CVSS >= {min_cvss}."
    return build_envelope("unreachable_cves", summary, rows)


def graph_summary() -> dict[str, Any]:
    """Node/relationship counts and which analytics stages have run."""
    with _read_session() as session:
        result = reachability.graph_summary(session)
    nodes = result["node_counts"]
    summary = (
        f"{nodes['File']} files, {nodes['Method']} methods, {nodes['CVE']} CVEs; "
        f"pagerank={'yes' if result['has_pagerank_score'] else 'no'}, "
        f"co_changed={'yes' if result['has_co_changed'] else 'no'}."
    )
    return build_envelope("graph_summary", summary, [result])


# --- App wiring --------------------------------------------------------------

# (function, one-line "what it answers") — the scope sentence is appended to
# every description so agents reading only the tool list see the Java-only +
# soundness ceiling.
_TOOL_SPECS: list[tuple[Any, str]] = [
    (
        cve_reachability,
        "Which of your Java methods can reach a given CVE's vulnerable dependency, "
        "with example call paths (ranked by confidence tier and hop distance).",
    ),
    (
        blast_radius,
        "What else tends to change with a file and who owns it: change-coupling "
        "co-change partners plus top committers and bus factor.",
    ),
    (
        hotspots,
        "Which files change most often and declare the highest-centrality methods "
        "(change frequency joined with peak method PageRank).",
    ),
    (
        ownership,
        "Who owns the code under a path or package: commits, files touched, last "
        "commit date, and each developer's share.",
    ),
    (
        risk_register,
        "The ranked CVE risk register — every AFFECTS-linked CVE with its "
        "reachability status (REACHABLE / FRONTIER_UNREACHABLE / NO_FRONTIER / "
        "NOT_IMPORTED). This is the pitch in one call.",
    ),
    (
        dependency_cves,
        "Which CVEs affect an exact Maven coordinate 'group:artifact:version', "
        "with CVSS, match type, and AFFECTS confidence.",
    ),
    (
        unreachable_cves,
        "Which CVEs have no reachable call path (NOT_IMPORTED / NO_FRONTIER / "
        "FRONTIER_UNREACHABLE), each with an evidence string for safe dismissal.",
    ),
    (
        graph_summary,
        "Node/relationship counts per label/type plus flags for the pagerank and "
        "CO_CHANGED stages and the latest commit date — self-diagnose an unrun "
        "pipeline stage instead of misreading empty results.",
    ),
]


def build_app(namespace: str | None = None) -> FastMCP:
    """Build the FastMCP app and register all eight tools.

    ``namespace`` (default: ``CODEGRAPH_MCP_NAMESPACE`` env) prefixes every tool
    name. Building the app performs no I/O and no database connection.
    """
    if namespace is None:
        namespace = os.getenv(NAMESPACE_ENV)
    app = FastMCP(
        "code-graph",
        instructions=(
            "Curated, read-only risk queries over a neo4j-code-graph database "
            "(CVE reachability, blast radius, ownership, hotspots). Every result "
            "is a versioned envelope with in-band caveats. " + SCOPE_SENTENCE
        ),
    )
    for fn, answers in _TOOL_SPECS:
        description = f"{answers}\n\n{SCOPE_SENTENCE}"
        app.tool(name=namespaced_tool_name(fn.__name__, namespace), description=description)(fn)
    return app


def main() -> None:
    """Entry point for ``code-graph-mcp``: run the server over stdio."""
    app = build_app()
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
