#!/usr/bin/env python3
"""Ranked CVE risk register built on the reachability module.

``code-graph-risk-report`` turns dependency-level CVE flags into a ranked
risk register: for every AFFECTS-linked CVE it classifies reachability
(REACHABLE / FRONTIER_UNREACHABLE / NO_FRONTIER / NOT_IMPORTED), scores the
reachable ones, and attaches call-path evidence, change-coupling blast radius,
and ownership for the headline frontier method.

Scoring (constants in ``src/constants.py``)::

    risk_score = cvss * tier_weight * hop_factor
    hop_factor = 1 / (1 + RISK_HOP_DECAY * min_hops)

``tier_weight`` follows the frontier confidence tier
(``RISK_TIER_WEIGHTS``: HIGH 1.0, MEDIUM 0.7, LOW 0.4). Rows without a
reachable frontier get tier ``NONE`` (weight 0.05, hop_factor 1.0), sort to
the bottom, and carry the label "no call-path evidence — deprioritize, not
proof of safety". Blast radius (co-change partner count of the frontier
file) and staleness (days since its last commit) are sort TIEBREAKERS only,
never score multipliers: sort by risk_score desc, then co_change_count desc,
then staleness desc.

Soundness framing: this is a ranked triage aid with confidence tiers, not
proof of (un)reachability — see the fixed footer emitted by
:func:`to_markdown` and ``docs/reachability.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

try:
    from src.constants import (  # type: ignore[attr-defined]
        DEFAULT_MAX_HOPS,
        RISK_HOP_DECAY,
        RISK_TIER_WEIGHTS,
    )
    from src.security import reachability
    from src.utils.common import (
        add_common_args,
        create_neo4j_driver,
        resolve_neo4j_args,
        setup_logging,
    )
except Exception:  # pragma: no cover - installed package execution path
    from constants import DEFAULT_MAX_HOPS, RISK_HOP_DECAY, RISK_TIER_WEIGHTS  # type: ignore
    from security import reachability  # type: ignore
    from utils.common import (  # type: ignore
        add_common_args,
        create_neo4j_driver,
        resolve_neo4j_args,
        setup_logging,
    )

logger = logging.getLogger(__name__)

__all__ = [
    "CONFIDENCE_RANKS",
    "TIER_NONE",
    "NO_EVIDENCE_NOTE",
    "RiskRow",
    "RiskReport",
    "compute_risk_score",
    "sort_and_rank",
    "min_confidence_rank",
    "parse_entry_sets",
    "generate_risk_report",
    "to_json",
    "to_markdown",
    "write_report",
    "main",
]

# --min-confidence label -> confidence_rank threshold on CALLS_EXTERNAL edges.
CONFIDENCE_RANKS: dict[str, int] = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

# Tier assigned to rows without a reachable frontier (weight in
# RISK_TIER_WEIGHTS); such rows always sort below rows with evidence.
TIER_NONE = "NONE"

# Fixed label carried by every TIER_NONE row (absence of evidence is not
# proof of safety — see module docstring).
NO_EVIDENCE_NOTE = "no call-path evidence — deprioritize, not proof of safety"


# --- Report structures (mirror the documented JSON schema) -------------------


class DependencyInfo(TypedDict):
    """Maven coordinates of the affected dependency."""

    group_id: str | None
    artifact_id: str | None
    version: str | None


class AffectsInfo(TypedDict):
    """Provenance of the CVE->dependency AFFECTS link."""

    confidence: float | None
    match_type: str | None


class FrontierMethodInfo(TypedDict):
    """Headline frontier method (best confidence, then min hops)."""

    signature: str
    file: str | None
    line: int | None


class ReachabilityInfo(TypedDict):
    """Reachability classification and call-path evidence for one CVE."""

    status: str
    confidence_tier: str
    min_hops: int | None
    frontier_method: FrontierMethodInfo | None
    evidence: list[dict[str, Any]]
    example_paths: list[dict[str, Any]]


class BlastRadiusInfo(TypedDict):
    """Change-coupling blast radius of the headline frontier file."""

    co_change_count: int
    co_changed_files: list[dict[str, Any]]


class OwnershipInfo(TypedDict):
    """Ownership of the headline frontier file."""

    top_committers: list[dict[str, Any]]
    last_touched: str | None
    bus_factor: int | None


class ScoreComponents(TypedDict):
    """Transparent breakdown of risk_score plus the sort tiebreakers."""

    cvss: float
    tier_weight: float
    hop_factor: float
    tiebreak_blast_radius: int
    tiebreak_staleness_days: int


class ReportParameters(TypedDict):
    """Generation parameters echoed into the report."""

    max_hops: int
    entry_sets: list[str]
    min_confidence: str
    risk_threshold: float


class ReportSummary(TypedDict):
    """Per-status CVE counts and the headline triage reduction."""

    cves_dep_level: int
    cves_with_reachable_frontier: int
    cves_no_frontier: int
    cves_frontier_unreachable: int
    cves_not_imported: int
    triage_reduction_pct: float


@dataclass
class RiskRow:
    """One ranked risk-register entry (one CVE)."""

    rank: int
    cve_id: str
    cvss_score: float
    severity: str | None
    dependency: DependencyInfo
    affects: AffectsInfo
    reachability: ReachabilityInfo
    blast_radius: BlastRadiusInfo
    ownership: OwnershipInfo
    risk_score: float
    score_components: ScoreComponents
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize with a fixed, documented key order."""
        return {
            "rank": self.rank,
            "cve_id": self.cve_id,
            "cvss_score": self.cvss_score,
            "severity": self.severity,
            "dependency": dict(self.dependency),
            "affects": dict(self.affects),
            "reachability": dict(self.reachability),
            "blast_radius": dict(self.blast_radius),
            "ownership": dict(self.ownership),
            "risk_score": self.risk_score,
            "score_components": dict(self.score_components),
            "note": self.note,
        }


@dataclass
class RiskReport:
    """The full report: metadata, parameters, summary, ranked register."""

    generated_at: str
    database: str
    tool_version: str
    parameters: ReportParameters
    summary: ReportSummary
    risk_register: list[RiskRow]

    def to_dict(self) -> dict[str, Any]:
        """Serialize with a fixed, documented key order."""
        return {
            "generated_at": self.generated_at,
            "database": self.database,
            "tool_version": self.tool_version,
            "parameters": dict(self.parameters),
            "summary": dict(self.summary),
            "risk_register": [row.to_dict() for row in self.risk_register],
        }


# --- Pure helpers -------------------------------------------------------------


def min_confidence_rank(label: str) -> int:
    """Map a --min-confidence label (LOW|MEDIUM|HIGH) to its edge rank (1|2|3)."""
    try:
        return CONFIDENCE_RANKS[label.upper()]
    except KeyError:
        raise ValueError(
            f"min_confidence must be one of {sorted(CONFIDENCE_RANKS)}, got {label!r}"
        ) from None


def parse_entry_sets(value: str) -> tuple[str, ...]:
    """Parse a csv of entry-set names, validating against the known sets."""
    sets = tuple(dict.fromkeys(s.strip() for s in value.split(",") if s.strip()))
    if not sets:
        raise ValueError(
            f"--entry-set must name at least one of: {', '.join(reachability.VALID_ENTRY_SETS)}"
        )
    unknown = [s for s in sets if s not in reachability.VALID_ENTRY_SETS]
    if unknown:
        raise ValueError(
            f"Unknown entry set(s) {unknown!r}; valid: {list(reachability.VALID_ENTRY_SETS)}"
        )
    return sets


def compute_risk_score(cvss: float, tier: str, min_hops: int | None) -> tuple[float, float, float]:
    """Return ``(risk_score, tier_weight, hop_factor)`` for one row.

    ``tier`` is HIGH/MEDIUM/LOW (frontier confidence) or NONE (no reachable
    frontier). NONE rows — and any row without a hop count — use
    ``hop_factor = 1.0``; NONE's deprioritization comes solely from its 0.05
    tier weight.
    """
    try:
        tier_weight = float(RISK_TIER_WEIGHTS[tier])
    except KeyError:
        raise ValueError(
            f"Unknown confidence tier {tier!r}; valid: {sorted(RISK_TIER_WEIGHTS)}"
        ) from None
    if tier == TIER_NONE or min_hops is None:
        hop_factor = 1.0
    else:
        hop_factor = 1.0 / (1.0 + RISK_HOP_DECAY * float(min_hops))
    risk_score = round(cvss * tier_weight * hop_factor, 4)
    return risk_score, tier_weight, round(hop_factor, 4)


def sort_and_rank(rows: list[RiskRow]) -> list[RiskRow]:
    """Order the register and assign 1-based ranks (mutates ``rank`` in place).

    Sort: rows with call-path evidence before TIER_NONE rows, then
    risk_score desc, then co_change_count desc, then staleness days desc
    (tiebreakers only — never score multipliers), then cve_id asc for
    determinism.
    """

    def key(row: RiskRow) -> tuple[int, float, int, int, str]:
        components = row.score_components
        return (
            1 if row.reachability["confidence_tier"] == TIER_NONE else 0,
            -row.risk_score,
            -int(components["tiebreak_blast_radius"] or 0),
            -int(components["tiebreak_staleness_days"] or 0),
            row.cve_id,
        )

    ordered = sorted(rows, key=key)
    for rank, row in enumerate(ordered, start=1):
        row.rank = rank
    return ordered


def _staleness_days(last_touched: str | None, now: datetime) -> int:
    """Days since ``last_touched`` (ISO-8601 string from Neo4j), floored at 0."""
    if not last_touched:
        return 0
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(last_touched.replace("Z", "+00:00"))
    except ValueError:
        try:  # fall back to the date part (e.g. nanosecond precision strings)
            parsed = datetime.fromisoformat(last_touched[:10])
        except ValueError:
            return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, (now - parsed).days)


def _tool_version() -> str:
    """Installed package version, or 'dev' when running from a checkout."""
    try:
        from importlib.metadata import version

        return version("neo4j-code-graph")
    except Exception:
        return "dev"


def _empty_reachability(status: str) -> ReachabilityInfo:
    """Reachability block for rows without a reachable frontier."""
    return {
        "status": status,
        "confidence_tier": TIER_NONE,
        "min_hops": None,
        "frontier_method": None,
        "evidence": [],
        "example_paths": [],
    }


def _empty_blast_radius() -> BlastRadiusInfo:
    """Blast-radius block for rows without a headline frontier file."""
    return {"co_change_count": 0, "co_changed_files": []}


def _empty_ownership() -> OwnershipInfo:
    """Ownership block for rows without a headline frontier file."""
    return {"top_committers": [], "last_touched": None, "bus_factor": None}


# --- Report generation --------------------------------------------------------


def _dependency_and_affects(
    linked_rows: list[dict[str, Any]],
    group_id: str | None = None,
    artifact_id: str | None = None,
) -> tuple[DependencyInfo, AffectsInfo]:
    """Pick the dependency/AFFECTS info for a row from its linked_cves rows.

    When ``group_id``/``artifact_id`` are given (from the headline frontier
    row), prefer the matching linked row; otherwise fall back to the first
    (linked_cves orders by CVSS desc, then ids).
    """
    chosen: dict[str, Any] | None = None
    if group_id is not None or artifact_id is not None:
        for row in linked_rows:
            if row.get("group_id") == group_id and row.get("artifact_id") == artifact_id:
                chosen = row
                break
    if chosen is None and linked_rows:
        chosen = linked_rows[0]
    if chosen is None:
        return (
            {"group_id": group_id, "artifact_id": artifact_id, "version": None},
            {"confidence": None, "match_type": None},
        )
    return (
        {
            "group_id": chosen.get("group_id"),
            "artifact_id": chosen.get("artifact_id"),
            "version": chosen.get("version"),
        },
        {
            "confidence": chosen.get("affects_confidence"),
            "match_type": chosen.get("match_type"),
        },
    )


def generate_risk_report(
    session: Any,
    database: str,
    *,
    cve_ids: Sequence[str] | None = None,
    risk_threshold: float = 0.0,
    max_hops: int = DEFAULT_MAX_HOPS,
    entry_sets: Sequence[str] = reachability.DEFAULT_ENTRY_SETS,
    entry_annotations: list[str] | None = None,
    min_confidence: str = "LOW",
    top: int = 50,
    max_paths_per_cve: int = 3,
    now: datetime | None = None,
) -> RiskReport:
    """Build the full risk report from an open Neo4j session.

    Uses :func:`reachability.triage_summary` for per-CVE classification, then
    per REACHABLE CVE re-runs :func:`reachability.reachability_for_cve` to
    pick the headline frontier row (best confidence, then min hops) and
    fetches :func:`reachability.blast_radius_ownership` for its file.
    Non-reachable rows keep their status with null/empty frontier, blast
    radius, and ownership blocks.
    """
    now = now or datetime.now(timezone.utc)
    min_rank = min_confidence_rank(min_confidence)
    entry_set_list = list(entry_sets)

    triage = reachability.triage_summary(
        session,
        risk_threshold=float(risk_threshold),
        max_hops=max_hops,
        entry_sets=entry_set_list,
        entry_annotations=entry_annotations,
        min_confidence_rank=min_rank,
    )
    linked_by_cve: dict[str, list[dict[str, Any]]] = {}
    for row in reachability.linked_cves(session, min_cvss=float(risk_threshold)):
        linked_by_cve.setdefault(row["id"], []).append(row)

    triage_rows = triage["cves"]
    if cve_ids:
        wanted = set(cve_ids)
        triage_rows = [r for r in triage_rows if r["cve_id"] in wanted]

    rows: list[RiskRow] = []
    for cve_row in triage_rows:
        cve_id = cve_row["cve_id"]
        status = cve_row["status"]
        cvss = float(cve_row["cvss_score"]) if cve_row.get("cvss_score") is not None else 0.0
        linked_rows = linked_by_cve.get(cve_id, [])

        if status == reachability.STATUS_REACHABLE:
            reach_rows = reachability.reachability_for_cve(
                session,
                cve_id,
                max_hops=max_hops,
                entry_sets=entry_set_list,
                entry_annotations=entry_annotations,
                min_confidence_rank=min_rank,
                max_example_paths=max_paths_per_cve,
            )
        else:
            reach_rows = []

        if reach_rows:
            # Query orders by confidence_rank desc, min_hops asc: row 0 is
            # the headline frontier.
            headline = reach_rows[0]
            tier = headline["confidence"]
            min_hops = int(headline["min_hops"])
            frontier_file = headline.get("frontier_file")
            reach_info: ReachabilityInfo = {
                "status": status,
                "confidence_tier": tier,
                "min_hops": min_hops,
                "frontier_method": {
                    "signature": headline["frontier_method"],
                    "file": frontier_file,
                    "line": headline.get("frontier_line"),
                },
                "evidence": list(headline.get("evidence") or []),
                "example_paths": list(headline.get("example_routes") or []),
            }
            if frontier_file:
                blast = reachability.blast_radius_ownership(session, frontier_file)
                blast_info: BlastRadiusInfo = {
                    "co_change_count": blast["co_change_count"],
                    "co_changed_files": blast["co_changed_files"][:5],
                }
                ownership_info: OwnershipInfo = {
                    "top_committers": blast["ownership"]["top_committers"],
                    "last_touched": blast["ownership"]["last_touched"],
                    "bus_factor": blast["ownership"]["bus_factor"],
                }
            else:  # pragma: no cover - frontier methods always carry a file
                blast_info = _empty_blast_radius()
                ownership_info = _empty_ownership()
            dependency, affects = _dependency_and_affects(
                linked_rows, headline.get("group_id"), headline.get("artifact_id")
            )
            note = None
        else:
            tier = TIER_NONE
            min_hops = None
            reach_info = _empty_reachability(status)
            blast_info = _empty_blast_radius()
            ownership_info = _empty_ownership()
            dependency, affects = _dependency_and_affects(linked_rows)
            note = NO_EVIDENCE_NOTE

        risk_score, tier_weight, hop_factor = compute_risk_score(cvss, tier, min_hops)
        components: ScoreComponents = {
            "cvss": cvss,
            "tier_weight": tier_weight,
            "hop_factor": hop_factor,
            "tiebreak_blast_radius": blast_info["co_change_count"],
            "tiebreak_staleness_days": _staleness_days(ownership_info["last_touched"], now),
        }
        rows.append(
            RiskRow(
                rank=0,
                cve_id=cve_id,
                cvss_score=cvss,
                severity=cve_row.get("severity"),
                dependency=dependency,
                affects=affects,
                reachability=reach_info,
                blast_radius=blast_info,
                ownership=ownership_info,
                risk_score=risk_score,
                score_components=components,
                note=note,
            )
        )

    ordered = sort_and_rank(rows)
    if top and top > 0:
        ordered = ordered[:top]

    # Summary recomputed from the built rows so a --cve filter stays
    # consistent with the register (matches triage_summary when unfiltered).
    statuses = [r.reachability["status"] for r in rows]
    total = len(statuses)
    reachable = statuses.count(reachability.STATUS_REACHABLE)
    summary: ReportSummary = {
        "cves_dep_level": total,
        "cves_with_reachable_frontier": reachable,
        "cves_no_frontier": statuses.count(reachability.STATUS_NO_FRONTIER),
        "cves_frontier_unreachable": statuses.count(reachability.STATUS_FRONTIER_UNREACHABLE),
        "cves_not_imported": statuses.count(reachability.STATUS_NOT_IMPORTED),
        "triage_reduction_pct": round(100.0 * (total - reachable) / total, 1) if total else 0.0,
    }
    parameters: ReportParameters = {
        "max_hops": int(max_hops),
        "entry_sets": entry_set_list,
        "min_confidence": min_confidence.upper(),
        "risk_threshold": float(risk_threshold),
    }
    return RiskReport(
        generated_at=now.isoformat(timespec="seconds"),
        database=database,
        tool_version=_tool_version(),
        parameters=parameters,
        summary=summary,
        risk_register=ordered,
    )


# --- Renderers ------------------------------------------------------------------


def to_json(report: RiskReport) -> str:
    """Render the report as pretty-printed JSON with deterministic key order."""
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


_SOUNDNESS_FOOTER = f"""## Soundness

This report is a **ranked triage aid with confidence tiers, not proof of
(un)reachability**. CALLS edges are matched by receiver class + arity only —
no full type resolution. Invisible to this analysis:

- reflection (`Class.forName`, `Method.invoke`) and runtime classloading
- dependency-injection / runtime wiring beyond declared field and parameter types
- dynamic dispatch to subtypes (declared type != runtime type)
- chained/fluent receivers (`a.b().c()`), lambdas and method references (`Foo::bar`)
- `import static` calls and files with multiple external wildcard imports
- transitive-dependency API surface re-exported through a direct dependency
- shaded/relocated packages

Rows without a reachable frontier are kept, down-weighted, and labeled
"{NO_EVIDENCE_NOTE}"."""


def _format_dependency(dep: DependencyInfo) -> str:
    """Compact ``group:artifact:version`` label for tables."""
    if not any(dep.values()):
        return "unknown"
    return ":".join(str(part) if part else "?" for part in dep.values())


def _summary_header_md(report: RiskReport) -> str:
    """Markdown summary header shared by the file renderer and the console."""
    s = report.summary
    p = report.parameters
    lines = [
        "# CVE Risk Report",
        "",
        f"Generated {report.generated_at} | database `{report.database}` | "
        f"tool {report.tool_version}",
        "",
        f"**{s['cves_dep_level']} dependency-level CVEs -> "
        f"{s['cves_with_reachable_frontier']} with a reachable call-path frontier "
        f"({s['triage_reduction_pct']}% triage reduction).**",
        "",
        f"Status breakdown: {s['cves_with_reachable_frontier']} REACHABLE, "
        f"{s['cves_frontier_unreachable']} FRONTIER_UNREACHABLE, "
        f"{s['cves_no_frontier']} NO_FRONTIER, "
        f"{s['cves_not_imported']} NOT_IMPORTED.",
        "",
        f"Parameters: max_hops={p['max_hops']}, "
        f"entry_sets={','.join(p['entry_sets'])}, "
        f"min_confidence={p['min_confidence']}, "
        f"risk_threshold={p['risk_threshold']}",
    ]
    return "\n".join(lines)


def _register_table_md(rows: list[RiskRow]) -> str:
    """Markdown ranked-register table (header always present)."""
    lines = [
        "| # | CVE | CVSS | Dependency | Status | Tier | Hops | Frontier method "
        "| Blast radius | Owner (last touch) | Score |",
        "|---|-----|------|------------|--------|------|------|-----------------"
        "|--------------|--------------------|-------|",
    ]
    for row in rows:
        frontier = row.reachability["frontier_method"]
        frontier_cell = f"`{frontier['signature']}`" if frontier else "-"
        hops = row.reachability["min_hops"]
        hops_cell = str(hops) if hops is not None else "-"
        committers = row.ownership["top_committers"]
        if committers:
            touch = (row.ownership["last_touched"] or "")[:10]
            owner_cell = f"{committers[0].get('email', '?')} ({touch})"
        else:
            owner_cell = "-"
        lines.append(
            f"| {row.rank} | {row.cve_id} | {row.cvss_score} "
            f"| {_format_dependency(row.dependency)} | {row.reachability['status']} "
            f"| {row.reachability['confidence_tier']} | {hops_cell} | {frontier_cell} "
            f"| {row.blast_radius['co_change_count']} | {owner_cell} | {row.risk_score} |"
        )
    if len(lines) == 2:
        lines.append("")
        lines.append("_No CVEs with AFFECTS links found._")
    return "\n".join(lines)


def _format_path(example_path: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    """Render one example path: ``entry -> a -> b -> frontier => [import#method()]``."""
    chain = " -> ".join(f"`{sig}`" for sig in example_path.get("path", []))
    if evidence:
        first = evidence[0]
        chain += f" => [{first.get('import_path', '?')}#{first.get('method_name', '?')}()]"
    return chain


def _detail_blocks_md(rows: list[RiskRow], limit: int = 10) -> str:
    """Per-CVE detail blocks for the top ``limit`` REACHABLE rows."""
    reachable = [r for r in rows if r.reachability["status"] == reachability.STATUS_REACHABLE]
    if not reachable:
        return ""
    lines = ["## Call-path evidence (top reachable CVEs)"]
    for row in reachable[:limit]:
        r = row.reachability
        frontier = r["frontier_method"] or {"signature": "?", "file": None, "line": None}
        lines.append("")
        lines.append(
            f"### {row.rank}. {row.cve_id} — CVSS {row.cvss_score} "
            f"{row.severity or ''} — risk {row.risk_score}".rstrip()
        )
        lines.append("")
        affects_bits = []
        if row.affects["confidence"] is not None:
            affects_bits.append(f"confidence {row.affects['confidence']}")
        if row.affects["match_type"]:
            affects_bits.append(str(row.affects["match_type"]))
        affects_note = f" (AFFECTS {', '.join(affects_bits)})" if affects_bits else ""
        lines.append(f"- Dependency: `{_format_dependency(row.dependency)}`{affects_note}")
        lines.append(
            f"- Frontier: `{frontier['signature']}` "
            f"({frontier['file']}:{frontier['line']}) — tier {r['confidence_tier']}, "
            f"min {r['min_hops']} hop(s)"
        )
        if r["example_paths"]:
            lines.append(f"- Path: {_format_path(r['example_paths'][0], r['evidence'])}")
        partners = ", ".join(
            p["path"] for p in row.blast_radius["co_changed_files"][:3] if p.get("path")
        )
        lines.append(
            f"- Blast radius: {row.blast_radius['co_change_count']} co-changed file(s)"
            + (f" (top: {partners})" if partners else "")
        )
        committers = row.ownership["top_committers"]
        if committers:
            top = committers[0]
            lines.append(
                f"- Ownership: {top.get('email', '?')} ({top.get('commits', '?')} commits), "
                f"last touched {(row.ownership['last_touched'] or '?')[:10]}, "
                f"bus factor {row.ownership['bus_factor']}"
            )
        else:
            lines.append("- Ownership: no git history for the frontier file")
    return "\n".join(lines)


def to_markdown(report: RiskReport) -> str:
    """Render the full Markdown report (summary, table, details, footer)."""
    parts = [
        _summary_header_md(report),
        "",
        "## Risk register",
        "",
        _register_table_md(report.risk_register),
    ]
    details = _detail_blocks_md(report.risk_register)
    if details:
        parts.extend(["", details])
    parts.extend(["", _SOUNDNESS_FOOTER, ""])
    return "\n".join(parts)


def write_report(report: RiskReport, output_prefix: str, fmt: str) -> list[Path]:
    """Write ``<prefix>.json`` / ``<prefix>.md`` per ``fmt``; return the paths."""
    prefix = Path(output_prefix)
    if prefix.parent and not prefix.parent.exists():
        prefix.parent.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if fmt in ("json", "both"):
        json_path = prefix.with_name(prefix.name + ".json")
        json_path.write_text(to_json(report) + "\n", encoding="utf-8")
        written.append(json_path)
    if fmt in ("markdown", "both"):
        md_path = prefix.with_name(prefix.name + ".md")
        md_path.write_text(to_markdown(report), encoding="utf-8")
        written.append(md_path)
    return written


# --- CLI ------------------------------------------------------------------------


def main() -> None:
    """Entry point for the ``code-graph-risk-report`` command."""
    parser = argparse.ArgumentParser(
        description="Generate a ranked CVE risk register with call-path reachability evidence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full register, JSON + Markdown next to the current directory
  code-graph-risk-report

  # One CVE, markdown only, custom output prefix
  code-graph-risk-report --cve CVE-2020-36518 --format markdown --output reports/jackson

  # High-severity slice with a stricter frontier
  code-graph-risk-report --risk-threshold 7.0 --min-confidence MEDIUM --entry-set annotated
        """,
    )
    add_common_args(parser)
    parser.add_argument(
        "--cve",
        action="append",
        dest="cves",
        metavar="CVE_ID",
        help="Restrict to this CVE id (repeatable; default: all AFFECTS-linked CVEs)",
    )
    parser.add_argument(
        "--risk-threshold",
        type=float,
        default=0.0,
        help="Minimum CVSS score to include (default: 0.0)",
    )
    parser.add_argument(
        "--max-hops",
        type=int,
        default=DEFAULT_MAX_HOPS,
        help=f"Maximum internal CALLS hops entry->frontier (default: {DEFAULT_MAX_HOPS})",
    )
    parser.add_argument(
        "--entry-set",
        default=",".join(reachability.DEFAULT_ENTRY_SETS),
        help="Comma-separated entry sets: annotated,main,public (default: annotated,main)",
    )
    parser.add_argument(
        "--entry-annotations",
        default=None,
        help="Comma-separated annotation names overriding the default entry annotations",
    )
    parser.add_argument(
        "--min-confidence",
        choices=sorted(CONFIDENCE_RANKS, key=CONFIDENCE_RANKS.get),  # type: ignore[arg-type]
        default="LOW",
        help="Minimum CALLS_EXTERNAL confidence tier for frontier evidence (default: LOW)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="both",
        help="Output format(s) to write (default: both)",
    )
    parser.add_argument(
        "--output",
        default="./risk_report",
        help="Output path prefix; writes <prefix>.json / <prefix>.md (default: ./risk_report)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Keep at most this many ranked rows in the register (default: 50)",
    )
    parser.add_argument(
        "--max-paths-per-cve",
        type=int,
        default=3,
        help="Example call paths recorded per CVE (default: 3)",
    )
    args = parser.parse_args()

    setup_logging(args.log_level, args.log_file)
    try:
        entry_sets = parse_entry_sets(args.entry_set)
    except ValueError as exc:
        parser.error(str(exc))
    entry_annotations = None
    if args.entry_annotations:
        entry_annotations = [a.strip() for a in args.entry_annotations.split(",") if a.strip()]

    uri, username, password, database = resolve_neo4j_args(
        args.uri, args.username, args.password, args.database
    )
    logger.info("Generating risk report from %s (database %s)", uri, database)
    with create_neo4j_driver(uri, username, password) as driver:
        with driver.session(database=database) as session:
            report = generate_risk_report(
                session,
                database=database,
                cve_ids=args.cves,
                risk_threshold=args.risk_threshold,
                max_hops=args.max_hops,
                entry_sets=entry_sets,
                entry_annotations=entry_annotations,
                min_confidence=args.min_confidence,
                top=args.top,
                max_paths_per_cve=args.max_paths_per_cve,
            )

    written = write_report(report, args.output, args.format)
    print(_summary_header_md(report))
    print()
    print(_register_table_md(report.risk_register[:10]))
    print()
    for path in written:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
