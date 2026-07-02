#!/usr/bin/env python3
"""Canned Cypher for CVE method-level reachability triage.

Single source of truth for the reachability queries consumed by the
``code-graph-risk-report`` CLI and the MCP server. Both import this module;
neither re-embeds query text.

Graph shapes consumed (all written by the ingest pipeline):

- ``(:CVE)-[:AFFECTS {confidence, match_type}]->(:ExternalDependency)``
- ``(:Import)-[:DEPENDS_ON]->(:ExternalDependency)``
- ``(:Method)-[:CALLS_EXTERNAL {method_name, target_class, confidence,
  confidence_rank, ...}]->(:Import)`` — the external-call *frontier*
- ``(:Method)-[:CALLS]->(:Method)`` — internal call graph
- ``(:Method|Class|Interface)-[:ANNOTATED]->(:Annotation {name})``
- ``(:File)-[:CO_CHANGED {support, confidence}]->(:File)`` (canonical
  direction ``f1.path < f2.path``)
- ``(:Developer)-[:AUTHORED]->(:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(:File)``

Soundness framing: the frontier is a *ranked triage signal with confidence
tiers*, not proof of (un)reachability. Reflection, DI wiring, dynamic
dispatch, chained/fluent receivers, method references, static imports, and
transitive-dependency API surface re-exported through a direct dependency
remain invisible.

All functions take an open Neo4j session, are print-free, and return plain
``list[dict]`` / ``dict`` values with stable snake_case keys.

Note on ``max_hops``: Cypher cannot parameterize variable-length pattern
bounds (``[:CALLS*0..$n]`` is invalid), so the validated, clamped integer is
interpolated into the query string. Everything else is parameterized.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

try:
    from src.constants import (  # type: ignore[attr-defined]
        DEFAULT_ENTRY_ANNOTATIONS,
        DEFAULT_MAX_HOPS,
    )
except Exception:  # pragma: no cover - installed package execution path
    from constants import DEFAULT_ENTRY_ANNOTATIONS, DEFAULT_MAX_HOPS  # type: ignore

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_ENTRY_SETS",
    "VALID_ENTRY_SETS",
    "MAX_HOPS_FLOOR",
    "MAX_HOPS_CEILING",
    "linked_cves",
    "frontier_for_cve",
    "reachability_for_cve",
    "triage_summary",
    "blast_radius_ownership",
    "hotspots",
    "ownership",
    "dependency_cves",
    "graph_summary",
]

# Var-length CALLS bounds interpolated into the flagship query. Floor 1 keeps
# at least direct entry->frontier paths; ceiling 12 caps the exponential
# blow-up of the bidirectional BFS on dense call graphs.
MAX_HOPS_FLOOR = 1
MAX_HOPS_CEILING = 12

DEFAULT_ENTRY_SETS: tuple[str, ...] = ("annotated", "main")

# CVE triage statuses (per-CVE classification in triage_summary).
STATUS_REACHABLE = "REACHABLE"
STATUS_FRONTIER_UNREACHABLE = "FRONTIER_UNREACHABLE"
STATUS_NO_FRONTIER = "NO_FRONTIER"
STATUS_NOT_IMPORTED = "NOT_IMPORTED"

_CONFIDENCE_LABEL_CASE = "CASE best_conf WHEN 3 THEN 'HIGH' WHEN 2 THEN 'MEDIUM' ELSE 'LOW' END"

# --- Entry-set predicate fragments -----------------------------------------
# Combined with OR over the selected entry sets; only these vetted fragments
# are ever interpolated (user input never reaches the query string).

# Method-level entry annotation, or a public method of a class/interface
# whose class-level annotation (e.g. @RestController, JAX-RS @Path) exposes
# its public methods.
_ENTRY_PREDICATE_ANNOTATED = """(
      EXISTS {
        MATCH (entry)-[:ANNOTATED]->(a:Annotation) WHERE a.name IN $entry_annotations
      }
      OR (
        entry.is_public = true
        AND EXISTS {
          MATCH (owner)-[:CONTAINS_METHOD]->(entry)
          WHERE (owner:Class OR owner:Interface)
            AND EXISTS {
              MATCH (owner)-[:ANNOTATED]->(ca:Annotation)
              WHERE ca.name IN $entry_annotations
            }
        }
      )
    )"""

_ENTRY_PREDICATE_MAIN = (
    "(entry.name = 'main' AND entry.is_static = true AND entry.is_public = true)"
)

# Conservative superset; expensive on large graphs (documented in
# reachability_for_cve). Excludes test methods by definition, independent of
# the include_tests flag.
_ENTRY_PREDICATE_PUBLIC = "(entry.is_public = true AND NOT coalesce(entry.is_test_method, false))"

_ENTRY_SET_PREDICATES = {
    "annotated": _ENTRY_PREDICATE_ANNOTATED,
    "main": _ENTRY_PREDICATE_MAIN,
    "public": _ENTRY_PREDICATE_PUBLIC,
}

# Public view of the valid entry-set names (CLI validation lives elsewhere;
# the predicate fragments themselves stay private).
VALID_ENTRY_SETS: tuple[str, ...] = tuple(sorted(_ENTRY_SET_PREDICATES))

# --- Canned queries ---------------------------------------------------------

LINKED_CVES_QUERY = """
MATCH (cve:CVE)-[aff:AFFECTS]->(dep:ExternalDependency)
WHERE coalesce(cve.cvss_score, 0.0) >= $min_cvss
RETURN cve.id AS id,
       cve.cvss_score AS cvss_score,
       cve.severity AS severity,
       dep.group_id AS group_id,
       dep.artifact_id AS artifact_id,
       dep.version AS version,
       aff.confidence AS affects_confidence,
       aff.match_type AS match_type
ORDER BY coalesce(cve.cvss_score, 0.0) DESC, id ASC, artifact_id ASC
"""

_FRONTIER_FOR_CVE_TEMPLATE = """
MATCH (cve:CVE {id: $cve_id})-[:AFFECTS]->(dep:ExternalDependency)
MATCH (imp:Import)-[:DEPENDS_ON]->(dep)
MATCH (frontier:Method)-[xc:CALLS_EXTERNAL]->(imp)
WHERE xc.confidence_rank >= $min_conf_rank
WITH frontier,
     collect(DISTINCT {import_path: imp.import_path, target_class: xc.target_class,
                       method_name: xc.method_name, confidence: xc.confidence}) AS evidence,
     max(xc.confidence_rank) AS best_conf
RETURN frontier.method_signature AS method_signature,
       frontier.file AS file,
       frontier.line AS line,
       best_conf AS confidence_rank,
       {conf_case} AS confidence,
       evidence
ORDER BY confidence_rank DESC, method_signature ASC
"""

FRONTIER_FOR_CVE_QUERY = _FRONTIER_FOR_CVE_TEMPLATE.replace("{conf_case}", _CONFIDENCE_LABEL_CASE)

# Flagship reachability query template. Placeholders filled by
# _build_reachability_query(); ONLY vetted fragments and a clamped int are
# interpolated — see module docstring for why max_hops cannot be a parameter.
_REACHABILITY_TEMPLATE_RAW = """
MATCH (cve:CVE {{id: $cve_id}})-[:AFFECTS]->(dep:ExternalDependency)
MATCH (imp:Import)-[:DEPENDS_ON]->(dep)
MATCH (frontier:Method)-[xc:CALLS_EXTERNAL]->(imp)
WHERE xc.confidence_rank >= $min_conf_rank
WITH cve, dep, frontier,
     collect(DISTINCT {{import_path: imp.import_path, target_class: xc.target_class,
                       method_name: xc.method_name, confidence: xc.confidence}})[0..5] AS evidence,
     max(xc.confidence_rank) AS best_conf
MATCH (entry:Method)
WHERE {test_filter}(
    {entry_predicate}
)
MATCH p = shortestPath((entry)-[:CALLS*0..{max_hops}]->(frontier))
WITH cve, dep, frontier, evidence, best_conf, entry, length(p) AS hops,
     [m IN nodes(p) | m.method_signature] AS route
ORDER BY hops ASC, entry.method_signature ASC
WITH cve, dep, frontier, evidence, best_conf,
     min(hops) AS min_hops,
     collect({{entry: entry.method_signature, hops: hops, path: route}})[0..$max_example_paths]
       AS example_routes
RETURN cve.id AS cve_id,
       cve.cvss_score AS cvss_score,
       cve.severity AS severity,
       dep.group_id AS group_id,
       dep.artifact_id AS artifact_id,
       dep.version AS version,
       frontier.method_signature AS frontier_method,
       frontier.file AS frontier_file,
       frontier.line AS frontier_line,
       best_conf AS confidence_rank,
       {conf_case} AS confidence,
       evidence,
       min_hops,
       example_routes
ORDER BY confidence_rank DESC, min_hops ASC, frontier_method ASC
"""

REACHABILITY_QUERY_TEMPLATE = _REACHABILITY_TEMPLATE_RAW.replace(
    "{conf_case}", _CONFIDENCE_LABEL_CASE
)

TRIAGE_BASE_QUERY = """
MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)
WHERE coalesce(cve.cvss_score, 0.0) >= $risk_threshold
OPTIONAL MATCH (imp:Import)-[:DEPENDS_ON]->(dep)
OPTIONAL MATCH (frontier:Method)-[xc:CALLS_EXTERNAL]->(imp)
WHERE xc.confidence_rank >= $min_conf_rank
WITH cve,
     count(DISTINCT dep) AS dependency_count,
     count(DISTINCT imp) AS import_count,
     count(DISTINCT frontier) AS frontier_method_count
RETURN cve.id AS cve_id,
       cve.cvss_score AS cvss_score,
       cve.severity AS severity,
       dependency_count,
       import_count,
       frontier_method_count
ORDER BY coalesce(cve.cvss_score, 0.0) DESC, cve_id ASC
"""

CO_CHANGED_PARTNERS_QUERY = """
MATCH (f:File {path: $file_path})-[cc:CO_CHANGED]-(partner:File)
WHERE cc.support >= $min_support
RETURN partner.path AS path,
       cc.support AS support,
       cc.confidence AS confidence
ORDER BY cc.support DESC, coalesce(cc.confidence, 0.0) DESC, path ASC
"""

FILE_COMMITTERS_QUERY = """
MATCH (f:File {path: $file_path})<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(c:Commit)
      <-[:AUTHORED]-(d:Developer)
WITH d, count(DISTINCT c) AS commits, max(c.date) AS last_touched
RETURN d.email AS email,
       d.name AS name,
       commits,
       toString(last_touched) AS last_touched
ORDER BY commits DESC, email ASC
"""

FILE_LAST_TOUCHED_QUERY = """
MATCH (:File {path: $file_path})<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(c:Commit)
RETURN toString(max(c.date)) AS last_touched
"""

# Change-frequency hotspots: files changed most in the window, joined with the
# peak method PageRank of the methods they declare. change_count is recomputed
# from the commit graph over the window (the same distinct-commit count the
# temporal stage persists onto File.change_count) so ``days`` stays meaningful
# even when that stage has not been run. peak_pagerank is null when centrality
# has not been run (see graph_summary()).
HOTSPOTS_QUERY = """
MATCH (f:File)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(c:Commit)
WHERE $days IS NULL OR c.date >= datetime() - duration({days: $days})
WITH f, count(DISTINCT c) AS change_count
WHERE change_count > 0
OPTIONAL MATCH (f)-[:DECLARES]->(m:Method)
WITH f, change_count, max(m.pagerank_score) AS peak_pagerank
RETURN f.path AS path,
       change_count,
       peak_pagerank
ORDER BY change_count DESC, coalesce(peak_pagerank, 0.0) DESC, path ASC
LIMIT $top_n
"""

# Ownership over a path prefix: distinct commits, distinct files touched, last
# commit date and per-developer share of the commits in scope. share sums to
# ~1.0 across the returned rows (each commit counted once per author).
OWNERSHIP_QUERY = """
MATCH (d:Developer)-[:AUTHORED]->(c:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f:File)
WHERE f.path STARTS WITH $path_prefix
  AND ($days IS NULL OR c.date >= datetime() - duration({days: $days}))
WITH d,
     count(DISTINCT c) AS commits,
     count(DISTINCT f) AS files_touched,
     max(c.date) AS last_commit_date
WITH collect({
       developer_email: d.email,
       developer_name: d.name,
       commits: commits,
       files_touched: files_touched,
       last_commit_date: toString(last_commit_date)
     }) AS devs,
     sum(commits) AS total
UNWIND devs AS dev
RETURN dev.developer_email AS developer_email,
       dev.developer_name AS developer_name,
       dev.commits AS commits,
       dev.files_touched AS files_touched,
       dev.last_commit_date AS last_commit_date,
       (CASE WHEN total > 0 THEN toFloat(dev.commits) / total ELSE 0.0 END) AS share
ORDER BY commits DESC, developer_email ASC
"""

# Direct CVE lookup for one exact Maven coordinate (group:artifact:version).
DEPENDENCY_CVES_QUERY = """
MATCH (cve:CVE)-[aff:AFFECTS]->(dep:ExternalDependency)
WHERE dep.group_id = $group_id
  AND dep.artifact_id = $artifact_id
  AND dep.version = $version
RETURN cve.id AS cve_id,
       cve.cvss_score AS cvss_score,
       cve.severity AS severity,
       aff.confidence AS affects_confidence,
       aff.match_type AS match_type,
       dep.group_id AS group_id,
       dep.artifact_id AS artifact_id,
       dep.version AS version
ORDER BY coalesce(cve.cvss_score, 0.0) DESC, cve_id ASC
"""

# Whole-graph census: node/relationship counts by label/type, plus flags for
# analytics stages (pagerank_score, CO_CHANGED) so an agent can tell "no rows"
# apart from "that pipeline stage has not run".
GRAPH_SUMMARY_COUNTS_QUERY = """
RETURN count{ (n:File) } AS files,
       count{ (n:Method) } AS methods,
       count{ (n:Class) } AS classes,
       count{ (n:Interface) } AS interfaces,
       count{ (n:Import) } AS imports,
       count{ (n:ExternalDependency) } AS external_dependencies,
       count{ (n:CVE) } AS cves,
       count{ (n:Commit) } AS commits,
       count{ (n:Developer) } AS developers,
       count{ (n:FileVer) } AS file_versions,
       count{ (n:Annotation) } AS annotations,
       count{ ()-[r:CALLS]->() } AS calls,
       count{ ()-[r:CALLS_EXTERNAL]->() } AS calls_external,
       count{ ()-[r:IMPORTS]->() } AS imports_edges,
       count{ ()-[r:DEPENDS_ON]->() } AS depends_on,
       count{ ()-[r:DECLARES]->() } AS declares,
       count{ ()-[r:AFFECTS]->() } AS affects,
       count{ ()-[r:CO_CHANGED]->() } AS co_changed,
       count{ ()-[r:AUTHORED]->() } AS authored,
       count{ ()-[r:CHANGED]->() } AS changed,
       count{ ()-[r:OF_FILE]->() } AS of_file,
       count{ ()-[r:ANNOTATED]->() } AS annotated,
       exists{ (m:Method) WHERE m.pagerank_score IS NOT NULL } AS has_pagerank_score
"""

GRAPH_SUMMARY_LATEST_COMMIT_QUERY = """
MATCH (c:Commit)
RETURN toString(max(c.date)) AS latest_commit_date
"""


# --- Validation / pure helpers ----------------------------------------------


def _validate_max_hops(max_hops: Any) -> int:
    """Validate and clamp the var-length bound that gets interpolated.

    Raises ``ValueError`` for anything that is not a plain int (bools
    included); clamps into [MAX_HOPS_FLOOR, MAX_HOPS_CEILING].
    """
    if isinstance(max_hops, bool) or not isinstance(max_hops, int):
        raise ValueError(f"max_hops must be an int, got {type(max_hops).__name__}: {max_hops!r}")
    return max(MAX_HOPS_FLOOR, min(MAX_HOPS_CEILING, max_hops))


def _bus_factor(counts: list[int]) -> int:
    """Smallest number of committers covering >= 50% of commits.

    ``counts`` are per-committer distinct-commit counts (any order). Returns 0
    for empty/zero history.
    """
    total = sum(counts)
    if total <= 0:
        return 0
    threshold = total / 2.0
    covered = 0
    for k, commits in enumerate(sorted(counts, reverse=True), start=1):
        covered += commits
        if covered >= threshold:
            return k
    return len(counts)  # pragma: no cover - unreachable (covered >= total/2 by then)


def _entry_predicate(entry_sets: Sequence[str]) -> str:
    """OR-combine the vetted predicate fragments for the selected entry sets."""
    sets = list(dict.fromkeys(entry_sets))  # dedupe, keep order
    if not sets:
        raise ValueError("entry_sets must contain at least one of: annotated, main, public")
    unknown = [s for s in sets if s not in _ENTRY_SET_PREDICATES]
    if unknown:
        raise ValueError(
            f"Unknown entry set(s) {unknown!r}; valid: {sorted(_ENTRY_SET_PREDICATES)}"
        )
    return "\n    OR ".join(_ENTRY_SET_PREDICATES[s] for s in sets)


def _build_reachability_query(max_hops: int, entry_sets: Sequence[str], include_tests: bool) -> str:
    """Render the flagship query from vetted fragments + a clamped int bound."""
    hops = _validate_max_hops(max_hops)
    test_filter = "" if include_tests else "NOT coalesce(entry.is_test_method, false)\n  AND "
    return REACHABILITY_QUERY_TEMPLATE.format(
        test_filter=test_filter,
        entry_predicate=_entry_predicate(entry_sets),
        max_hops=hops,
    )


# --- Query functions ---------------------------------------------------------


def linked_cves(session: Any, min_cvss: float = 0.0) -> list[dict[str, Any]]:
    """CVEs with AFFECTS edges and their dependencies (one row per CVE x dep).

    Keys: id, cvss_score, severity, group_id, artifact_id, version,
    affects_confidence, match_type.
    """
    result = session.run(LINKED_CVES_QUERY, min_cvss=float(min_cvss))
    return [dict(record) for record in result]


def frontier_for_cve(
    session: Any, cve_id: str, min_confidence_rank: int = 1
) -> list[dict[str, Any]]:
    """Frontier methods whose CALLS_EXTERNAL edges land in imports of the CVE's deps.

    One row per frontier method. Keys: method_signature, file, line,
    confidence_rank (best rank across its evidence edges), confidence
    (HIGH/MEDIUM/LOW label for that rank), evidence (list of
    {import_path, target_class, method_name, confidence}).
    """
    result = session.run(
        FRONTIER_FOR_CVE_QUERY,
        cve_id=cve_id,
        min_conf_rank=int(min_confidence_rank),
    )
    return [dict(record) for record in result]


def reachability_for_cve(
    session: Any,
    cve_id: str,
    max_hops: int = DEFAULT_MAX_HOPS,
    entry_sets: Sequence[str] = DEFAULT_ENTRY_SETS,
    entry_annotations: list[str] | None = None,
    min_confidence_rank: int = 1,
    max_example_paths: int = 3,
    include_tests: bool = False,
) -> list[dict[str, Any]]:
    """Entry-point reachability for a CVE's external-call frontier.

    For every frontier method (a method with CALLS_EXTERNAL evidence into an
    import of a dependency the CVE AFFECTS), find shortest CALLS paths from
    the selected entry frontier and return one row per (dependency, frontier
    method) that is reachable within ``max_hops``. Frontier methods with no
    entry path are absent from the result (that distinction powers
    FRONTIER_UNREACHABLE in :func:`triage_summary`).

    Entry sets (``entry_sets``, OR-combined):

    - ``"annotated"`` — method-level ANNOTATED to one of ``entry_annotations``,
      or a public method of a class/interface with a class-level entry
      annotation.
    - ``"main"`` — ``public static`` methods named ``main``.
    - ``"public"`` — every public non-test method. Conservative superset;
      expensive on large graphs (entry x frontier shortest-path cross
      product), use for completeness passes only.

    A frontier method that is itself an entry point yields ``min_hops = 0``
    (zero-length path). ``include_tests=False`` (default) excludes methods
    with ``is_test_method = true`` from the entry frontier.

    Row keys: cve_id, cvss_score, severity, group_id, artifact_id, version,
    frontier_method, frontier_file, frontier_line, confidence_rank,
    confidence, evidence, min_hops, example_routes (up to
    ``max_example_paths`` of {entry, hops, path}).
    """
    query = _build_reachability_query(max_hops, entry_sets, include_tests)
    annotations = list(
        entry_annotations if entry_annotations is not None else DEFAULT_ENTRY_ANNOTATIONS
    )
    result = session.run(
        query,
        cve_id=cve_id,
        min_conf_rank=int(min_confidence_rank),
        entry_annotations=annotations,
        max_example_paths=int(max_example_paths),
    )
    return [dict(record) for record in result]


def triage_summary(
    session: Any,
    risk_threshold: float = 0.0,
    max_hops: int = DEFAULT_MAX_HOPS,
    entry_sets: Sequence[str] = DEFAULT_ENTRY_SETS,
    entry_annotations: list[str] | None = None,
    min_confidence_rank: int = 1,
    include_tests: bool = False,
) -> dict[str, Any]:
    """Per-CVE reachability classification for every AFFECTS-linked CVE.

    Statuses:

    - ``REACHABLE`` — frontier exists and at least one entry path reaches it
      within ``max_hops``.
    - ``FRONTIER_UNREACHABLE`` — frontier exists but no entry path within
      ``max_hops``.
    - ``NO_FRONTIER`` — affected dependency is imported but has zero
      CALLS_EXTERNAL evidence (at ``min_confidence_rank``).
    - ``NOT_IMPORTED`` — no Import DEPENDS_ON any affected dependency.

    Returns ``{"cves": [...], "summary": {...}}`` where each CVE row carries
    cve_id, cvss_score, severity, status, dependency_count, import_count,
    frontier_method_count, reachable_frontier_count, min_hops; the summary
    carries per-status counts, total, and triage_reduction_pct (share of
    dep-level CVE flags with no reachable call path — the triage win over
    dependency-level flagging alone).
    """
    max_hops = _validate_max_hops(max_hops)
    base = session.run(
        TRIAGE_BASE_QUERY,
        risk_threshold=float(risk_threshold),
        min_conf_rank=int(min_confidence_rank),
    )
    cve_rows: list[dict[str, Any]] = []
    status_counts = {
        STATUS_REACHABLE: 0,
        STATUS_FRONTIER_UNREACHABLE: 0,
        STATUS_NO_FRONTIER: 0,
        STATUS_NOT_IMPORTED: 0,
    }
    for record in base:
        row = dict(record)
        row["reachable_frontier_count"] = 0
        row["min_hops"] = None
        if row["frontier_method_count"] == 0:
            row["status"] = STATUS_NO_FRONTIER if row["import_count"] > 0 else STATUS_NOT_IMPORTED
        else:
            reachable = reachability_for_cve(
                session,
                row["cve_id"],
                max_hops=max_hops,
                entry_sets=entry_sets,
                entry_annotations=entry_annotations,
                min_confidence_rank=min_confidence_rank,
                max_example_paths=1,
                include_tests=include_tests,
            )
            if reachable:
                row["status"] = STATUS_REACHABLE
                row["reachable_frontier_count"] = len({r["frontier_method"] for r in reachable})
                row["min_hops"] = min(r["min_hops"] for r in reachable)
            else:
                row["status"] = STATUS_FRONTIER_UNREACHABLE
        status_counts[row["status"]] += 1
        cve_rows.append(row)

    total = len(cve_rows)
    reachable_total = status_counts[STATUS_REACHABLE]
    reduction = (100.0 * (total - reachable_total) / total) if total else 0.0
    return {
        "cves": cve_rows,
        "summary": {
            "total": total,
            "reachable": reachable_total,
            "frontier_unreachable": status_counts[STATUS_FRONTIER_UNREACHABLE],
            "no_frontier": status_counts[STATUS_NO_FRONTIER],
            "not_imported": status_counts[STATUS_NOT_IMPORTED],
            "triage_reduction_pct": round(reduction, 1),
        },
    }


def blast_radius_ownership(
    session: Any, file_path: str, min_support: int = 2, top_committers: int = 5
) -> dict[str, Any]:
    """Change-coupling blast radius and ownership for one file.

    CO_CHANGED partners are matched in BOTH directions (edges are stored
    canonically with ``f1.path < f2.path``). Ownership lists the top
    committers by distinct commits (email, name, commits, last_touched as
    ISO-8601 string); ``bus_factor`` is the smallest number of committers
    covering >= 50% of the file's commits, computed over ALL committers.
    """
    partners = [
        dict(record)
        for record in session.run(
            CO_CHANGED_PARTNERS_QUERY, file_path=file_path, min_support=int(min_support)
        )
    ]
    committers = [
        dict(record) for record in session.run(FILE_COMMITTERS_QUERY, file_path=file_path)
    ]
    last_rec = session.run(FILE_LAST_TOUCHED_QUERY, file_path=file_path).single()
    last_touched = last_rec["last_touched"] if last_rec else None
    return {
        "file_path": file_path,
        "co_change_count": len(partners),
        "co_changed_files": partners,
        "ownership": {
            "top_committers": committers[: max(0, int(top_committers))],
            "total_commits": sum(c["commits"] for c in committers),
            "last_touched": last_touched,
            "bus_factor": _bus_factor([c["commits"] for c in committers]),
        },
    }


def hotspots(session: Any, days: int | None = 90, top_n: int = 20) -> list[dict[str, Any]]:
    """Change-frequency hotspots joined with peak method PageRank.

    Files with the most distinct commits in the last ``days`` (``None`` = all
    history), each joined with the maximum ``pagerank_score`` across the
    methods it declares. Rows: path, change_count, peak_pagerank
    (``peak_pagerank`` is null until the centrality stage has run). Ordered by
    change_count desc, then peak_pagerank desc. ``top_n`` caps the result.
    """
    result = session.run(
        HOTSPOTS_QUERY,
        days=(None if days is None else int(days)),
        top_n=int(top_n),
    )
    return [dict(record) for record in result]


def ownership(session: Any, path_prefix: str, days: int | None = None) -> list[dict[str, Any]]:
    """Per-developer ownership of files under a path prefix.

    Matches ``Developer-[:AUTHORED]->Commit-[:CHANGED]->FileVer-[:OF_FILE]->File``
    where ``File.path`` starts with ``path_prefix`` (optionally windowed to the
    last ``days``). Rows: developer_email, developer_name, commits,
    files_touched, last_commit_date (ISO-8601 string), share (fraction of the
    in-scope commits authored, ~sums to 1.0). Ordered by commits desc.
    """
    result = session.run(
        OWNERSHIP_QUERY,
        path_prefix=path_prefix,
        days=(None if days is None else int(days)),
    )
    return [dict(record) for record in result]


def dependency_cves(
    session: Any, group_id: str, artifact_id: str, version: str
) -> list[dict[str, Any]]:
    """CVEs AFFECTS an exact Maven coordinate (group:artifact:version).

    One row per CVE. Keys: cve_id, cvss_score, severity, affects_confidence,
    match_type, group_id, artifact_id, version. Ordered by CVSS desc.
    """
    result = session.run(
        DEPENDENCY_CVES_QUERY,
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
    )
    return [dict(record) for record in result]


def graph_summary(session: Any) -> dict[str, Any]:
    """Whole-graph census for self-diagnosing an unrun pipeline stage.

    Returns node_counts and relationship_counts (per label / type), the
    booleans has_pagerank_score (centrality stage) and has_co_changed
    (temporal-coupling stage), and latest_commit_date (ISO-8601 string or
    ``None``). Lets an agent distinguish an empty result from a pipeline stage
    that has not been run yet.
    """
    counts_rec = session.run(GRAPH_SUMMARY_COUNTS_QUERY).single()
    counts = dict(counts_rec) if counts_rec is not None else {}
    latest_rec = session.run(GRAPH_SUMMARY_LATEST_COMMIT_QUERY).single()
    latest_commit_date = latest_rec["latest_commit_date"] if latest_rec is not None else None

    def _c(key: str) -> int:
        return int(counts.get(key, 0) or 0)

    node_counts = {
        "File": _c("files"),
        "Method": _c("methods"),
        "Class": _c("classes"),
        "Interface": _c("interfaces"),
        "Import": _c("imports"),
        "ExternalDependency": _c("external_dependencies"),
        "CVE": _c("cves"),
        "Commit": _c("commits"),
        "Developer": _c("developers"),
        "FileVer": _c("file_versions"),
        "Annotation": _c("annotations"),
    }
    relationship_counts = {
        "CALLS": _c("calls"),
        "CALLS_EXTERNAL": _c("calls_external"),
        "IMPORTS": _c("imports_edges"),
        "DEPENDS_ON": _c("depends_on"),
        "DECLARES": _c("declares"),
        "AFFECTS": _c("affects"),
        "CO_CHANGED": _c("co_changed"),
        "AUTHORED": _c("authored"),
        "CHANGED": _c("changed"),
        "OF_FILE": _c("of_file"),
        "ANNOTATED": _c("annotated"),
    }
    return {
        "node_counts": node_counts,
        "relationship_counts": relationship_counts,
        "has_pagerank_score": bool(counts.get("has_pagerank_score", False)),
        "has_co_changed": relationship_counts["CO_CHANGED"] > 0,
        "latest_commit_date": latest_commit_date,
    }
