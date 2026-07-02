#!/usr/bin/env python3
"""External-call frontier writer: ``(:Method)-[:CALLS_EXTERNAL]->(:Import)``.

Method calls whose receiver/qualifier resolves to an externally-imported type
were previously discarded by ``create_method_calls`` (its ``WHERE callee IS
NOT NULL`` filters only keep calls that land on internal ``:Method`` nodes).
This module materializes those calls as frontier edges into the ``:Import``
node of the external API, with a confidence tier describing how the target
package was resolved:

- ``HIGH`` (rank 3): static or constructor call whose type is pinned by an
  exact fully-qualified import (``resolution == "explicit_import"``).
- ``MEDIUM`` (rank 2): instance call whose receiver's *declared* type was
  resolved in-file (local variable, parameter, or field) and that type is
  explicit-imported. Declared type != runtime type (dynamic dispatch caveat).
- ``LOW`` (rank 1): type resolved only via a single external wildcard import
  (package guessed).

Calls into ``java.*`` / ``javax.*`` are skipped outright (the JDK is not an
external dependency). Reflection, DI/runtime wiring, chained/fluent receivers,
method references, and static imports remain invisible — the frontier is a
ranked triage signal, not proof of (un)reachability.

Idempotency: re-running the writer over identical ``files_data`` is a no-op.
Call counts are aggregated per (caller signature, import path, callee name)
BEFORE writing; ``ON CREATE`` sets the aggregate, and ``ON MATCH`` keeps
``max(confidence_rank)`` / ``max(call_count)`` instead of incrementing, so
repeated ingests of the same snapshot cannot inflate counts.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

try:
    _batching = import_module("src.utils.batching")
except Exception:  # pragma: no cover
    _batching = import_module("utils.batching")
get_database_batch_size = _batching.get_database_batch_size

try:
    _progress = import_module("src.utils.progress")
except Exception:  # pragma: no cover
    _progress = import_module("utils.progress")
progress_range = _progress.progress_range

try:
    _parser = import_module("src.analysis.parser")
except Exception:  # pragma: no cover
    _parser = import_module("analysis.parser")
build_method_signature = _parser.build_method_signature

logger = logging.getLogger(__name__)

# JDK packages are never frontier edges: they are not externally-supplied
# dependencies and carry no GAV/CVE identity.
_JDK_PREFIXES = ("java.", "javax.")

_CONFIDENCE_RANKS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

# One edge per (caller, import, callee name). ON MATCH keeps max semantics so
# re-running over the same files_data leaves the graph unchanged (idempotent).
_MERGE_CALLS_EXTERNAL_CYPHER = """
UNWIND $rows AS row
MATCH (m:Method {method_signature: row.sig})
MATCH (i:Import {import_path: row.import_path})
MERGE (m)-[r:CALLS_EXTERNAL {method_name: row.method_name}]->(i)
ON CREATE SET r.target_class = row.target_class,
              r.call_type = row.call_type,
              r.confidence = row.confidence,
              r.confidence_rank = row.rank,
              r.resolution = row.resolution,
              r.receiver_source = row.receiver_source,
              r.call_count = row.n
ON MATCH SET r.confidence = CASE WHEN row.rank > r.confidence_rank
                                 THEN row.confidence ELSE r.confidence END,
             r.confidence_rank = CASE WHEN row.rank > r.confidence_rank
                                      THEN row.rank ELSE r.confidence_rank END,
             r.call_count = CASE WHEN row.n > r.call_count
                                 THEN row.n ELSE r.call_count END
"""


def _method_signature(file_data: dict[str, Any], method: dict[str, Any]) -> str | None:
    """Return the method's signature, computing it if the extractor didn't.

    Reuses :func:`src.analysis.parser.build_method_signature` (the exact
    helper the Method writer keys nodes with) rather than duplicating the
    format. The package is recovered from the file's type declarations.
    """
    sig = method.get("method_signature")
    if sig:
        return str(sig)
    package: str | None = None
    types = list(file_data.get("classes") or []) + list(file_data.get("interfaces") or [])
    for t in types:
        if t.get("name") == method.get("class_name") and t.get("package"):
            package = str(t["package"])
            break
    if package is None:
        for t in types:
            if t.get("package"):
                package = str(t["package"])
                break
    try:
        return str(
            build_method_signature(
                package,
                method.get("class_name"),
                method.get("name", ""),
                method.get("parameters") or [],
                method.get("return_type"),
            )
        )
    except Exception:  # pragma: no cover - defensive
        return None


def _collect_external_call_rows(
    files_data: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Aggregate external-call rows from extracted files_data (pure; no DB).

    Returns ``(rows, stats)`` where rows are aggregated per (caller signature,
    import path, callee method name) with a ``n`` call count and the highest
    applicable confidence tier, ready for the UNWIND MERGE.
    """
    aggregated: dict[tuple[str, str, str], dict[str, Any]] = {}
    stats = {
        "total_calls": 0,
        "unresolved_candidates": 0,
        "jdk_skipped": 0,
    }

    for file_data in files_data:
        explicit_external: set[str] = set()
        wildcard_external_bases: set[str] = set()
        for imp in file_data.get("imports", []) or []:
            if imp.get("import_type") != "external":
                continue
            path = str(imp.get("import_path") or "")
            if not path:
                continue
            if imp.get("is_wildcard"):
                wildcard_external_bases.add(path)
            else:
                explicit_external.add(path)

        for method in file_data.get("methods", []) or []:
            calls = method.get("calls", []) or []
            if not calls:
                continue
            sig = _method_signature(file_data, method)
            for call in calls:
                stats["total_calls"] += 1
                resolution = call.get("resolution")
                target_class = call.get("target_class")
                target_package = call.get("target_package")
                method_name = call.get("method_name")
                if resolution == "unresolved":
                    # Strict resolver miss: any package present is a lenient
                    # fallback (e.g. constructor same-package default) and must
                    # never be trusted as external evidence.
                    stats["unresolved_candidates"] += 1
                    continue
                if not sig or not method_name or not target_class or not target_package:
                    continue
                if str(target_package).startswith(_JDK_PREFIXES):
                    stats["jdk_skipped"] += 1
                    continue

                call_type = call.get("call_type")
                receiver_source = call.get("receiver_source")
                fqcn = f"{target_package}.{target_class}"
                if fqcn in explicit_external:
                    import_path = fqcn
                    if call_type in ("static", "constructor") and resolution == "explicit_import":
                        confidence = "HIGH"
                    else:
                        # Instance calls with an in-file declared receiver type
                        # (local/param/field), plus any explicit-import match
                        # whose resolution provenance is unknown.
                        confidence = "MEDIUM"
                elif str(target_package) in wildcard_external_bases or (
                    resolution == "wildcard_import"
                ):
                    # Package guessed from the file's single external wildcard.
                    import_path = str(target_package)
                    confidence = "LOW"
                else:
                    # Internal, unmatched, or standard-library type: not frontier.
                    continue

                rank = _CONFIDENCE_RANKS[confidence]
                key = (sig, import_path, str(method_name))
                row = aggregated.get(key)
                if row is None:
                    aggregated[key] = {
                        "sig": sig,
                        "import_path": import_path,
                        "method_name": str(method_name),
                        "target_class": str(target_class),
                        "call_type": call_type,
                        "confidence": confidence,
                        "rank": rank,
                        "resolution": resolution,
                        "receiver_source": receiver_source,
                        "n": 1,
                    }
                else:
                    row["n"] += 1
                    if rank > row["rank"]:
                        row["confidence"] = confidence
                        row["rank"] = rank
                        row["target_class"] = str(target_class)
                        row["call_type"] = call_type
                        row["resolution"] = resolution
                        row["receiver_source"] = receiver_source

    return list(aggregated.values()), stats


def create_external_calls(session: Any, files_data: list[dict[str, Any]]) -> None:
    """MERGE ``(:Method)-[:CALLS_EXTERNAL]->(:Import)`` frontier edges.

    Must run after ``create_imports`` (Import nodes must exist) and after
    ``create_methods`` (Method nodes are matched by ``method_signature``).

    ON MATCH semantics (idempotent by design): the edge keeps
    ``max(confidence_rank)`` (and its matching ``confidence`` label) and
    ``max(call_count)`` — counts are aggregated per caller/import/callee
    BEFORE writing, so re-running over identical files_data is a no-op
    rather than an increment.
    """
    rows, stats = _collect_external_call_rows(files_data)
    logger.info(
        "External-call frontier: %d calls scanned -> %d CALLS_EXTERNAL rows "
        "(%d unresolved external candidates skipped, %d JDK calls skipped)",
        stats["total_calls"],
        len(rows),
        stats["unresolved_candidates"],
        stats["jdk_skipped"],
    )
    if not rows:
        return

    batch_size = get_database_batch_size(has_embeddings=False)
    total_batches = (len(rows) + batch_size - 1) // batch_size
    for i in progress_range(
        0, len(rows), batch_size, total=total_batches, desc="CALLS_EXTERNAL rels"
    ):
        batch = rows[i : i + batch_size]
        session.run(_MERGE_CALLS_EXTERNAL_CYPHER, rows=batch)
