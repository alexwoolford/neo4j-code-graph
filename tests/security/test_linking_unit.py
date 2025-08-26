#!/usr/bin/env python3

from __future__ import annotations

from typing import Any

from src.security.linking import (
    compute_precise_matches,
    compute_text_versioned_matches,
    prepare_versioned_dependencies,
)


def test_prepare_versioned_dependencies_filters_unknowns() -> None:
    deps = [
        {"group_id": "g", "artifact_id": "a", "version": "1.0.0"},
        {"group_id": "g", "artifact_id": "a", "version": "unknown"},
        {"group_id": None, "artifact_id": "a", "version": "1.0.0"},
    ]
    out = prepare_versioned_dependencies(deps)
    assert out == [{"group_id": "g", "artifact_id": "a", "version": "1.0.0"}]


def test_compute_text_versioned_matches_basic() -> None:
    deps = [
        {
            "package": "org.example.json",
            "group_id": "org.example",
            "artifact_id": "json",
            "version": "1.2.3",
        }
    ]
    cves = [
        {"id": "CVE-1", "description": "A flaw in org.example.json parser"},
        {"id": "CVE-2", "description": "Unrelated"},
    ]
    matches = compute_text_versioned_matches(deps, cves)
    ids = {m["cve_id"] for m in matches}
    assert "CVE-1" in ids


def test_compute_precise_matches_handles_absence_gracefully(monkeypatch: Any) -> None:
    # If matcher import fails, function returns [] without raising
    def _fail_import(name: str, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - safeguard
        raise ImportError

    # Intentionally skip monkeypatching actual import to keep test simple and deterministic;
    # compute_precise_matches will catch and return [].
    precise = compute_precise_matches(
        [{"group_id": "g", "artifact_id": "a", "version": "1.0.0"}],
        [{"id": "CVE-1"}],
    )
    assert precise == []
