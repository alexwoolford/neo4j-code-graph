#!/usr/bin/env python3

from __future__ import annotations

import sys
import types
from typing import Any

from src.security.linking import compute_precise_matches


class _FakeGAV:
    def __init__(self, g: str, a: str, v: str):
        # Mirror the real GAVCoordinate attribute names: compute_precise_matches
        # reads gav.group_id / gav.artifact_id when building match rows.
        self.group_id, self.artifact_id, self.version = g, a, v


class _FakeMatcher:
    @staticmethod
    def match_gav_to_cve(gav: _FakeGAV, cve: dict[str, Any]) -> float | None:  # noqa: D401
        # return a confidence only for a specific ID
        return 0.9 if cve.get("id") == "CVE-OK" and gav.artifact_id == "json" else None


def test_compute_precise_matches_positive_path(monkeypatch) -> None:
    # compute_precise_matches imports gav_cve_matcher lazily; imports consult
    # sys.modules first, so a scoped setitem injects the fake and monkeypatch
    # restores the real module afterwards.
    fake = types.ModuleType("src.security.gav_cve_matcher")
    fake.GAVCoordinate = _FakeGAV  # type: ignore[attr-defined]
    fake.PreciseGAVMatcher = _FakeMatcher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.security.gav_cve_matcher", fake)

    deps = [
        {
            "group_id": "org.example",
            "artifact_id": "json",
            "version": "1.2.3",
            "package": "org.example.json",
        }
    ]
    cves = [{"id": "CVE-OK"}, {"id": "CVE-NOPE"}]

    matches = compute_precise_matches(deps, cves)
    assert any(m["cve_id"] == "CVE-OK" and m["match_type"] == "precise_gav" for m in matches)
