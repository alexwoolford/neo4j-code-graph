#!/usr/bin/env python3
"""Fast unit tests for src/security/risk_report.py (no database)."""

import json

import pytest

from src.constants import RISK_HOP_DECAY, RISK_TIER_WEIGHTS
from src.security.risk_report import (
    NO_EVIDENCE_NOTE,
    TIER_NONE,
    RiskReport,
    RiskRow,
    compute_risk_score,
    min_confidence_rank,
    parse_entry_sets,
    sort_and_rank,
    to_json,
    to_markdown,
)

# --- Fixture builders --------------------------------------------------------


def _make_row(
    cve_id="CVE-2099-0001",
    cvss=9.8,
    tier="HIGH",
    status="REACHABLE",
    min_hops=2,
    co_change_count=0,
    staleness_days=0,
    risk_score=None,
):
    """Construct a RiskRow with sensible defaults for scoring/sorting tests."""
    if tier == TIER_NONE:
        min_hops = None
    score, tier_weight, hop_factor = compute_risk_score(cvss, tier, min_hops)
    if risk_score is not None:
        score = risk_score
    reachable = tier != TIER_NONE
    return RiskRow(
        rank=0,
        cve_id=cve_id,
        cvss_score=cvss,
        severity="CRITICAL",
        dependency={
            "group_id": "com.example",
            "artifact_id": "widget",
            "version": "1.0.0",
        },
        affects={"confidence": 0.95, "match_type": "precise_gav"},
        reachability={
            "status": status,
            "confidence_tier": tier,
            "min_hops": min_hops,
            "frontier_method": (
                {
                    "signature": "com.example.JsonUtil#parse():void",
                    "file": "src/main/java/com/example/JsonUtil.java",
                    "line": 42,
                }
                if reachable
                else None
            ),
            "evidence": (
                [
                    {
                        "import_path": "com.fasterxml.jackson.databind.ObjectMapper",
                        "target_class": "ObjectMapper",
                        "method_name": "readValue",
                        "confidence": tier,
                    }
                ]
                if reachable
                else []
            ),
            "example_paths": (
                [
                    {
                        "entry": "com.example.PaymentController#handle():void",
                        "hops": min_hops,
                        "path": [
                            "com.example.PaymentController#handle():void",
                            "com.example.PaymentService#process():void",
                            "com.example.JsonUtil#parse():void",
                        ],
                    }
                ]
                if reachable
                else []
            ),
        },
        blast_radius={
            "co_change_count": co_change_count,
            "co_changed_files": [],
        },
        ownership={
            "top_committers": (
                [{"email": "alice@example.com", "name": "Alice", "commits": 3}] if reachable else []
            ),
            "last_touched": "2024-06-20T09:00:00Z" if reachable else None,
            "bus_factor": 1 if reachable else None,
        },
        risk_score=score,
        score_components={
            "cvss": cvss,
            "tier_weight": tier_weight,
            "hop_factor": hop_factor,
            "tiebreak_blast_radius": co_change_count,
            "tiebreak_staleness_days": staleness_days,
        },
        note=None if reachable else NO_EVIDENCE_NOTE,
    )


def _make_report(rows):
    """Wrap rows into a RiskReport with representative metadata."""
    statuses = [r.reachability["status"] for r in rows]
    total = len(rows)
    reachable = statuses.count("REACHABLE")
    return RiskReport(
        generated_at="2026-07-02T12:00:00+00:00",
        database="neo4j",
        tool_version="1.0.0",
        parameters={
            "max_hops": 6,
            "entry_sets": ["annotated", "main"],
            "min_confidence": "LOW",
            "risk_threshold": 0.0,
        },
        summary={
            "cves_dep_level": total,
            "cves_with_reachable_frontier": reachable,
            "cves_no_frontier": statuses.count("NO_FRONTIER"),
            "cves_frontier_unreachable": statuses.count("FRONTIER_UNREACHABLE"),
            "cves_not_imported": statuses.count("NOT_IMPORTED"),
            "triage_reduction_pct": (
                round(100.0 * (total - reachable) / total, 1) if total else 0.0
            ),
        },
        risk_register=sort_and_rank(rows),
    )


# --- Scoring math -------------------------------------------------------------


class TestComputeRiskScore:
    def test_direct_high_call_is_full_cvss(self):
        score, weight, hop_factor = compute_risk_score(9.8, "HIGH", 0)
        assert score == pytest.approx(9.8)
        assert weight == 1.0
        assert hop_factor == 1.0

    def test_hop_decay(self):
        score, _, hop_factor = compute_risk_score(9.8, "HIGH", 2)
        expected_factor = 1.0 / (1.0 + RISK_HOP_DECAY * 2)
        assert hop_factor == pytest.approx(expected_factor, abs=1e-4)
        assert score == pytest.approx(9.8 * expected_factor, abs=1e-3)

    @pytest.mark.parametrize("tier", ["HIGH", "MEDIUM", "LOW"])
    def test_tier_weights_applied(self, tier):
        score, weight, _ = compute_risk_score(10.0, tier, 0)
        assert weight == RISK_TIER_WEIGHTS[tier]
        assert score == pytest.approx(10.0 * RISK_TIER_WEIGHTS[tier])

    def test_none_tier_uses_hop_factor_one(self):
        score, weight, hop_factor = compute_risk_score(9.8, TIER_NONE, None)
        assert weight == RISK_TIER_WEIGHTS["NONE"] == 0.05
        assert hop_factor == 1.0
        assert score == pytest.approx(9.8 * 0.05)

    def test_six_hops_roughly_halves(self):
        _, _, hop_factor = compute_risk_score(10.0, "HIGH", 6)
        assert hop_factor == pytest.approx(1.0 / 1.9, abs=1e-4)

    def test_unknown_tier_rejected(self):
        with pytest.raises(ValueError):
            compute_risk_score(9.8, "BOGUS", 1)


# --- Sorting / ranking --------------------------------------------------------


class TestSortAndRank:
    def test_score_descending(self):
        rows = [
            _make_row(cve_id="CVE-1", cvss=5.0, min_hops=0),
            _make_row(cve_id="CVE-2", cvss=9.8, min_hops=0),
        ]
        ordered = sort_and_rank(rows)
        assert [r.cve_id for r in ordered] == ["CVE-2", "CVE-1"]
        assert [r.rank for r in ordered] == [1, 2]

    def test_none_tier_sorts_last_even_with_higher_score(self):
        # NONE row scores 10.0*0.05 = 0.5; the LOW row at 6 hops scores
        # 1.0*0.4/1.9 ~= 0.21 — lower, but it has call-path evidence, so it
        # must still outrank the NONE row.
        rows = [
            _make_row(cve_id="CVE-NONE", cvss=10.0, tier=TIER_NONE, status="NO_FRONTIER"),
            _make_row(cve_id="CVE-LOW", cvss=1.0, tier="LOW", min_hops=6),
        ]
        ordered = sort_and_rank(rows)
        assert [r.cve_id for r in ordered] == ["CVE-LOW", "CVE-NONE"]

    def test_tiebreak_blast_radius(self):
        rows = [
            _make_row(cve_id="CVE-A", co_change_count=1),
            _make_row(cve_id="CVE-B", co_change_count=9),
        ]
        ordered = sort_and_rank(rows)
        assert [r.cve_id for r in ordered] == ["CVE-B", "CVE-A"]
        # equal risk_score by construction
        assert ordered[0].risk_score == ordered[1].risk_score

    def test_tiebreak_staleness_after_blast_radius(self):
        rows = [
            _make_row(cve_id="CVE-FRESH", co_change_count=3, staleness_days=10),
            _make_row(cve_id="CVE-STALE", co_change_count=3, staleness_days=400),
        ]
        ordered = sort_and_rank(rows)
        assert [r.cve_id for r in ordered] == ["CVE-STALE", "CVE-FRESH"]

    def test_deterministic_final_tiebreak_on_cve_id(self):
        rows = [
            _make_row(cve_id="CVE-B"),
            _make_row(cve_id="CVE-A"),
        ]
        ordered = sort_and_rank(rows)
        assert [r.cve_id for r in ordered] == ["CVE-A", "CVE-B"]

    def test_ranks_are_one_based_and_sequential(self):
        rows = [_make_row(cve_id=f"CVE-{i}", cvss=float(i)) for i in range(1, 5)]
        ordered = sort_and_rank(rows)
        assert [r.rank for r in ordered] == [1, 2, 3, 4]


# --- JSON schema / round-trip ---------------------------------------------------


TOP_LEVEL_KEYS = [
    "generated_at",
    "database",
    "tool_version",
    "parameters",
    "summary",
    "risk_register",
]
PARAMETER_KEYS = ["max_hops", "entry_sets", "min_confidence", "risk_threshold"]
SUMMARY_KEYS = [
    "cves_dep_level",
    "cves_with_reachable_frontier",
    "cves_no_frontier",
    "cves_frontier_unreachable",
    "cves_not_imported",
    "triage_reduction_pct",
]
ROW_KEYS = [
    "rank",
    "cve_id",
    "cvss_score",
    "severity",
    "dependency",
    "affects",
    "reachability",
    "blast_radius",
    "ownership",
    "risk_score",
    "score_components",
    "note",
]
REACHABILITY_KEYS = [
    "status",
    "confidence_tier",
    "min_hops",
    "frontier_method",
    "evidence",
    "example_paths",
]
SCORE_COMPONENT_KEYS = [
    "cvss",
    "tier_weight",
    "hop_factor",
    "tiebreak_blast_radius",
    "tiebreak_staleness_days",
]


class TestJsonRendering:
    def test_round_trip_and_key_order(self):
        report = _make_report(
            [
                _make_row(cve_id="CVE-1"),
                _make_row(cve_id="CVE-2", tier=TIER_NONE, status="NOT_IMPORTED"),
            ]
        )
        parsed = json.loads(to_json(report))
        assert parsed == report.to_dict()
        assert list(parsed.keys()) == TOP_LEVEL_KEYS
        assert list(parsed["parameters"].keys()) == PARAMETER_KEYS
        assert list(parsed["summary"].keys()) == SUMMARY_KEYS
        for row in parsed["risk_register"]:
            assert list(row.keys()) == ROW_KEYS
            assert list(row["reachability"].keys()) == REACHABILITY_KEYS
            assert list(row["score_components"].keys()) == SCORE_COMPONENT_KEYS
            assert list(row["dependency"].keys()) == ["group_id", "artifact_id", "version"]
            assert list(row["affects"].keys()) == ["confidence", "match_type"]
            assert list(row["blast_radius"].keys()) == ["co_change_count", "co_changed_files"]
            assert list(row["ownership"].keys()) == [
                "top_committers",
                "last_touched",
                "bus_factor",
            ]

    def test_none_row_nulls_and_note(self):
        report = _make_report([_make_row(cve_id="CVE-X", tier=TIER_NONE, status="NO_FRONTIER")])
        row = json.loads(to_json(report))["risk_register"][0]
        assert row["reachability"]["status"] == "NO_FRONTIER"
        assert row["reachability"]["confidence_tier"] == "NONE"
        assert row["reachability"]["min_hops"] is None
        assert row["reachability"]["frontier_method"] is None
        assert row["reachability"]["evidence"] == []
        assert row["blast_radius"]["co_changed_files"] == []
        assert row["ownership"]["last_touched"] is None
        assert row["note"] == NO_EVIDENCE_NOTE

    def test_empty_register(self):
        report = _make_report([])
        parsed = json.loads(to_json(report))
        assert parsed["risk_register"] == []
        assert parsed["summary"]["cves_dep_level"] == 0
        assert parsed["summary"]["triage_reduction_pct"] == 0.0


# --- Markdown rendering ---------------------------------------------------------


class TestMarkdownRendering:
    def test_contains_summary_header_table_and_footer(self):
        report = _make_report(
            [
                _make_row(cve_id="CVE-2099-0001"),
                _make_row(cve_id="CVE-2099-0002", tier=TIER_NONE, status="NOT_IMPORTED"),
            ]
        )
        md = to_markdown(report)
        assert "# CVE Risk Report" in md
        assert "2 dependency-level CVEs -> 1 with a reachable call-path frontier" in md
        assert "50.0% triage reduction" in md
        assert "max_hops=6" in md
        # ranked table
        assert "| # | CVE | CVSS | Dependency | Status | Tier | Hops |" in md
        assert "| 1 | CVE-2099-0001 |" in md
        assert "| 2 | CVE-2099-0002 |" in md
        # detail block path rendering: entry -> ... -> frontier => [import#method()]
        assert "->" in md
        assert "=> [com.fasterxml.jackson.databind.ObjectMapper#readValue()]" in md
        # fixed soundness footer
        assert "## Soundness" in md
        assert "not proof of" in md
        assert "reflection" in md
        assert NO_EVIDENCE_NOTE in md

    def test_empty_register_does_not_crash(self):
        md = to_markdown(_make_report([]))
        assert "# CVE Risk Report" in md
        assert "_No CVEs with AFFECTS links found._" in md
        assert "## Soundness" in md

    def test_none_row_renders_dashes(self):
        report = _make_report([_make_row(cve_id="CVE-X", tier=TIER_NONE, status="NO_FRONTIER")])
        md = to_markdown(report)
        row_line = next(line for line in md.splitlines() if line.startswith("| 1 | CVE-X"))
        assert "| NONE |" in row_line
        assert "| - |" in row_line


# --- CLI helper parsing ---------------------------------------------------------


class TestMinConfidenceMapping:
    @pytest.mark.parametrize(
        "label,rank", [("LOW", 1), ("MEDIUM", 2), ("HIGH", 3), ("low", 1), ("high", 3)]
    )
    def test_mapping(self, label, rank):
        assert min_confidence_rank(label) == rank

    def test_invalid_label_rejected(self):
        with pytest.raises(ValueError):
            min_confidence_rank("EXTREME")


class TestParseEntrySets:
    def test_default_csv(self):
        assert parse_entry_sets("annotated,main") == ("annotated", "main")

    def test_single_and_whitespace(self):
        assert parse_entry_sets(" public ") == ("public",)
        assert parse_entry_sets("annotated , main") == ("annotated", "main")

    def test_dedupes_preserving_order(self):
        assert parse_entry_sets("main,annotated,main") == ("main", "annotated")

    def test_invalid_set_rejected(self):
        with pytest.raises(ValueError, match="bogus"):
            parse_entry_sets("annotated,bogus")

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            parse_entry_sets("")
        with pytest.raises(ValueError):
            parse_entry_sets(" , ")
