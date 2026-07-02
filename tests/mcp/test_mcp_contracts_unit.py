#!/usr/bin/env python3
"""Fast unit tests for the MCP response contract and pure helpers (no DB)."""

from __future__ import annotations

import pytest

from mcp_server.contracts import (
    JAVA_ONLY_CAVEAT,
    MAX_HOPS_CEILING,
    SOUNDNESS_CAVEAT,
    TOOL_SCHEMA_VERSION,
    build_envelope,
    namespaced_tool_name,
    parse_gav,
    validate_max_hops,
)


def test_schema_version_is_one_zero():
    assert TOOL_SCHEMA_VERSION == "1.0"


def test_build_envelope_shape_and_row_count():
    rows = [{"a": 1}, {"a": 2}, {"a": 3}]
    env = build_envelope("cve_reachability", "three rows", rows)

    assert env["schema_version"] == TOOL_SCHEMA_VERSION
    assert env["tool"] == "cve_reachability"
    assert env["summary"] == "three rows"
    assert env["row_count"] == len(rows) == 3
    assert env["truncated"] is False
    assert env["rows"] is rows


def test_build_envelope_caveats_include_java_and_soundness():
    env = build_envelope("graph_summary", "s", [])
    assert env["caveats"], "caveats must be non-empty"
    assert JAVA_ONLY_CAVEAT in env["caveats"]
    assert SOUNDNESS_CAVEAT in env["caveats"]
    # Java-only + soundness always lead the list.
    assert env["caveats"][0] == JAVA_ONLY_CAVEAT
    assert env["caveats"][1] == SOUNDNESS_CAVEAT


def test_build_envelope_extra_caveats_and_truncated():
    env = build_envelope("hotspots", "s", [{"x": 1}], truncated=True, extra_caveats=["extra note"])
    assert env["truncated"] is True
    assert "extra note" in env["caveats"]
    # Extra caveats append after the two standing caveats.
    assert env["caveats"][-1] == "extra note"
    assert JAVA_ONLY_CAVEAT in env["caveats"]


def test_row_count_matches_empty():
    env = build_envelope("unreachable_cves", "none", [])
    assert env["row_count"] == 0
    assert env["rows"] == []


def test_namespaced_tool_name_default_is_unchanged():
    assert namespaced_tool_name("cve_reachability", None) == "cve_reachability"
    assert namespaced_tool_name("cve_reachability", "") == "cve_reachability"
    assert namespaced_tool_name("cve_reachability", "   ") == "cve_reachability"


def test_namespaced_tool_name_applies_prefix():
    assert namespaced_tool_name("cve_reachability", "cg") == "cg_cve_reachability"
    # Whitespace is trimmed before prefixing.
    assert namespaced_tool_name("hotspots", "  team  ") == "team_hotspots"


def test_validate_max_hops_accepts_and_clamps():
    assert validate_max_hops(6) == 6
    assert validate_max_hops(1) == 1
    # Above the ceiling clamps down.
    assert validate_max_hops(999) == MAX_HOPS_CEILING


@pytest.mark.parametrize("bad", [0, -1, -5])
def test_validate_max_hops_rejects_non_positive(bad):
    with pytest.raises(ValueError):
        validate_max_hops(bad)


@pytest.mark.parametrize("bad", [True, False, 1.5, "6", None])
def test_validate_max_hops_rejects_non_int(bad):
    with pytest.raises(ValueError):
        validate_max_hops(bad)


def test_parse_gav_valid():
    assert parse_gav("org.example:vuln-lib:1.0.0") == ("org.example", "vuln-lib", "1.0.0")
    # Surrounding whitespace on parts is trimmed.
    assert parse_gav(" g : a : v ") == ("g", "a", "v")


@pytest.mark.parametrize(
    "bad",
    [
        "onlyone",
        "group:artifact",
        "g:a:v:extra",
        "g::v",
        ":a:v",
        "g:a:",
        "",
    ],
)
def test_parse_gav_rejects_bad_coordinates(bad):
    with pytest.raises(ValueError):
        parse_gav(bad)


def test_parse_gav_rejects_non_string():
    with pytest.raises(ValueError):
        parse_gav(123)  # type: ignore[arg-type]
