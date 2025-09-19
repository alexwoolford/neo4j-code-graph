#!/usr/bin/env python3

from __future__ import annotations

import builtins
from typing import Any

from src.security.linking import compute_precise_matches


class _FakeGAV:
    def __init__(self, g: str, a: str, v: str):
        self.g, self.a, self.v = g, a, v


class _FakeMatcher:
    @staticmethod
    def match_gav_to_cve(gav: _FakeGAV, cve: dict[str, Any]) -> float | None:  # noqa: D401
        # return a confidence only for a specific ID
        return 0.9 if cve.get("id") == "CVE-OK" and gav.a == "json" else None


def test_compute_precise_matches_positive_path(monkeypatch) -> None:
    # Monkeypatch import within function scope by injecting module symbols
    class _FakeModule:
        GAVCoordinate = _FakeGAV
        PreciseGAVMatcher = _FakeMatcher

    # Patch the exact import site used inside compute_precise_matches to avoid recursion
    def _fake_import(name: str, *args: Any, **kwargs: Any):  # pragma: no cover - guard
        if name == "src.security.gav_cve_matcher":
            return _FakeModule()
        return builtins.__import__(name, *args, **kwargs)

    monkeypatch.setattr("src.security.linking.__builtins__", "__import__", _fake_import)

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
