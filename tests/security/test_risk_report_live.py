#!/usr/bin/env python3
"""Live tests for the full risk-report generation pipeline.

Reuses the seeded miniature graph from tests/security/test_reachability_queries_live.py
(CVE-2099-0001 REACHABLE, CVE-2099-0002 NO_FRONTIER, CVE-2099-0003 NOT_IMPORTED)
and runs generate_risk_report + both renderers against a real Neo4j
(testcontainer via tests/conftest.py).
"""

import json

import pytest

from tests.security.test_reachability_queries_live import (
    DIRECT_FRONTIER_SIG,
    _get_driver_or_skip,
    _seed_graph,
)

pytestmark = pytest.mark.live


def _import_module():
    try:
        from src.security import risk_report
    except Exception:
        from security import risk_report  # type: ignore

    return risk_report


def _generate(session, database, module, **kwargs):
    return module.generate_risk_report(session, database=database, **kwargs)


def test_risk_report_generation_live(tmp_path):
    rr = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            report = _generate(session, database, rr)

            # --- summary consistent with the seeded statuses ----------------
            summary = report.summary
            assert summary["cves_dep_level"] == 3
            assert summary["cves_with_reachable_frontier"] == 1
            assert summary["cves_no_frontier"] == 1
            assert summary["cves_not_imported"] == 1
            assert summary["cves_frontier_unreachable"] == 0
            assert summary["triage_reduction_pct"] == pytest.approx(66.7, abs=0.1)

            register = report.risk_register
            assert len(register) == 3
            assert [row.rank for row in register] == [1, 2, 3]

            # --- REACHABLE row ranked first with the computed score ---------
            top = register[0]
            assert top.cve_id == "CVE-2099-0001"
            assert top.reachability["status"] == "REACHABLE"
            # Headline frontier: best confidence (HIGH), then min hops — the
            # annotated webhook method calls ObjectMapper directly (0 hops).
            assert top.reachability["confidence_tier"] == "HIGH"
            assert top.reachability["min_hops"] == 0
            assert top.reachability["frontier_method"]["signature"] == DIRECT_FRONTIER_SIG
            # risk_score = 9.8 * 1.0 * 1/(1 + 0.15*0) = 9.8
            assert top.risk_score == pytest.approx(9.8)
            assert top.score_components["tier_weight"] == 1.0
            assert top.score_components["hop_factor"] == 1.0
            assert top.dependency == {
                "group_id": "com.fasterxml.jackson.core",
                "artifact_id": "jackson-databind",
                "version": "2.9.10",
            }
            assert top.affects == {"confidence": 0.95, "match_type": "precise_gav"}
            assert top.reachability["evidence"][0]["method_name"] == "readTree"
            assert top.reachability["example_paths"][0]["path"] == [DIRECT_FRONTIER_SIG]
            assert top.note is None

            # --- NONE rows sorted below, NOT_IMPORTED at the bottom ---------
            middle, bottom = register[1], register[2]
            assert middle.cve_id == "CVE-2099-0002"
            assert middle.reachability["status"] == "NO_FRONTIER"
            assert middle.reachability["confidence_tier"] == "NONE"
            assert middle.risk_score == pytest.approx(8.1 * 0.05)

            assert bottom.cve_id == "CVE-2099-0003"
            assert bottom.reachability["status"] == "NOT_IMPORTED"
            assert bottom.reachability["confidence_tier"] == "NONE"
            assert bottom.risk_score == pytest.approx(7.5 * 0.05)
            assert bottom.reachability["frontier_method"] is None
            assert bottom.reachability["evidence"] == []
            assert bottom.blast_radius == {"co_change_count": 0, "co_changed_files": []}
            assert bottom.ownership["top_committers"] == []
            assert bottom.note == rr.NO_EVIDENCE_NOTE

            # --- renderers ---------------------------------------------------
            md = rr.to_markdown(report)
            assert "CVE-2099-0001" in md
            assert "## Soundness" in md
            assert "| 1 | CVE-2099-0001 |" in md

            parsed = json.loads(rr.to_json(report))
            assert parsed == report.to_dict()
            assert parsed["summary"]["cves_dep_level"] == 3
            assert parsed["risk_register"][0]["cve_id"] == "CVE-2099-0001"

            # --- write_report round-trips through the filesystem -------------
            written = rr.write_report(report, str(tmp_path / "risk_report"), "both")
            assert sorted(p.suffix for p in written) == [".json", ".md"]
            from_disk = json.loads((tmp_path / "risk_report.json").read_text(encoding="utf-8"))
            assert from_disk == report.to_dict()
            assert "# CVE Risk Report" in (tmp_path / "risk_report.md").read_text(encoding="utf-8")


def test_risk_report_headline_blast_radius_and_ownership_live():
    """When the headline frontier file has git history, blast/ownership populate."""
    rr = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            # Drop the direct (0-hop) frontier edge so the headline frontier
            # becomes JsonUtil#parse — the file with seeded history/co-changes.
            session.run(
                "MATCH (m:Method {method_signature: $sig})-[r:CALLS_EXTERNAL]->() DELETE r",
                sig=DIRECT_FRONTIER_SIG,
            ).consume()
            report = _generate(session, database, rr)

            top = report.risk_register[0]
            assert top.cve_id == "CVE-2099-0001"
            assert top.reachability["min_hops"] == 2
            # risk_score = 9.8 * 1.0 * 1/(1 + 0.15*2) = 9.8/1.3
            assert top.risk_score == pytest.approx(9.8 / 1.3, abs=1e-3)
            assert top.blast_radius["co_change_count"] == 2
            partner_paths = {p["path"] for p in top.blast_radius["co_changed_files"]}
            assert "src/main/java/com/example/Alpha.java" in partner_paths
            assert top.ownership["top_committers"][0]["email"] == "alice@example.com"
            assert top.ownership["bus_factor"] == 1
            assert top.ownership["last_touched"].startswith("2024-06-20")
            assert top.score_components["tiebreak_blast_radius"] == 2
            assert top.score_components["tiebreak_staleness_days"] > 0


def test_risk_report_cve_filter_and_min_confidence_live():
    rr = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            report = _generate(session, database, rr, cve_ids=["CVE-2099-0001"])
            assert [row.cve_id for row in report.risk_register] == ["CVE-2099-0001"]
            assert report.summary["cves_dep_level"] == 1
            assert report.summary["cves_with_reachable_frontier"] == 1
            assert report.summary["triage_reduction_pct"] == 0.0

            # HIGH threshold still finds the HIGH frontier edges
            high = _generate(session, database, rr, min_confidence="HIGH")
            top = high.risk_register[0]
            assert top.cve_id == "CVE-2099-0001"
            assert top.reachability["confidence_tier"] == "HIGH"
            assert high.parameters["min_confidence"] == "HIGH"
