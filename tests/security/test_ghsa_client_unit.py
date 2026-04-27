"""Unit tests for GHSA client conversion (no network calls)."""

from __future__ import annotations

from src.security.ghsa_client import _gha_to_clean_cve, _parse_ghsa_range


def test_parse_ghsa_range_pin() -> None:
    assert _parse_ghsa_range("= 1.2.3") == {
        "versionStartIncluding": "1.2.3",
        "versionEndIncluding": "1.2.3",
    }


def test_parse_ghsa_range_lower_bound_inclusive() -> None:
    assert _parse_ghsa_range(">= 1.2") == {"versionStartIncluding": "1.2"}


def test_parse_ghsa_range_lower_bound_exclusive() -> None:
    assert _parse_ghsa_range("> 1.2") == {"versionStartExcluding": "1.2"}


def test_parse_ghsa_range_upper_bound_inclusive() -> None:
    assert _parse_ghsa_range("<= 2.0") == {"versionEndIncluding": "2.0"}


def test_parse_ghsa_range_bounded() -> None:
    assert _parse_ghsa_range(">= 1.2, < 2.0") == {
        "versionStartIncluding": "1.2",
        "versionEndExcluding": "2.0",
    }


def test_parse_ghsa_range_malformed_returns_empty() -> None:
    assert _parse_ghsa_range("garbage") == {}
    assert _parse_ghsa_range("") == {}


def test_gha_to_clean_cve_extracts_maven_advisory() -> None:
    """A typical GHSA advisory for a Maven package converts to a CleanCVE-shaped dict."""
    advisory = {
        "ghsa_id": "GHSA-xxxx-yyyy-zzzz",
        "cve_id": "CVE-2099-99999",
        "summary": "Test advisory for jackson-core",
        "severity": "high",
        "cvss": {"score": 7.5},
        "published_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-02-01T00:00:00Z",
        "vulnerabilities": [
            {
                "package": {
                    "ecosystem": "maven",
                    "name": "com.fasterxml.jackson.core:jackson-core",
                },
                "vulnerable_version_range": ">= 2.13.0, < 2.15.0",
            }
        ],
    }
    cve = _gha_to_clean_cve(advisory)
    assert cve is not None
    assert cve["id"] == "CVE-2099-99999"
    assert cve["severity"] == "HIGH"
    assert cve["cvss_score"] == 7.5
    assert cve["_source"] == "ghsa"
    # Configurations contain a CPE-shaped entry that the matcher can consume
    assert len(cve["configurations"]) == 1
    nodes = cve["configurations"][0]["nodes"]
    assert any(
        node["cpeMatch"][0]["criteria"].startswith(
            "cpe:2.3:a:com.fasterxml.jackson.core:jackson-core"
        )
        for node in nodes
    )
    cpe = nodes[0]["cpeMatch"][0]
    assert cpe["versionStartIncluding"] == "2.13.0"
    assert cpe["versionEndExcluding"] == "2.15.0"


def test_gha_to_clean_cve_skips_non_maven() -> None:
    """Non-Maven advisories are skipped (this project is Java-only)."""
    advisory = {
        "ghsa_id": "GHSA-aaaa-bbbb-cccc",
        "cve_id": "CVE-2099-11111",
        "summary": "npm advisory",
        "severity": "low",
        "vulnerabilities": [
            {
                "package": {"ecosystem": "npm", "name": "express"},
                "vulnerable_version_range": "< 4.0.0",
            }
        ],
    }
    assert _gha_to_clean_cve(advisory) is None


def test_gha_to_clean_cve_falls_back_to_ghsa_id_when_no_cve() -> None:
    """Some GHSA advisories don't have a CVE id assigned yet."""
    advisory = {
        "ghsa_id": "GHSA-only-1234-5678",
        "cve_id": None,
        "summary": "GHSA-only advisory",
        "severity": "medium",
        "vulnerabilities": [
            {
                "package": {"ecosystem": "maven", "name": "org.example:lib"},
                "vulnerable_version_range": ">= 1.0",
            }
        ],
    }
    cve = _gha_to_clean_cve(advisory)
    assert cve is not None
    assert cve["id"] == "GHSA-only-1234-5678"
