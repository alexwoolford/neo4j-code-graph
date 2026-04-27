"""GitHub Security Advisories (GHSA) client.

Provides a complementary vulnerability source alongside NVD/CPE. GHSA covers
ecosystem-native advisories that may pre-date or supplement NVD entries.

The public GitHub Advisory Database is queryable without auth at modest rate
limits. Setting GITHUB_TOKEN raises the rate limit substantially; the client
reads it from env if present.

API doc: https://docs.github.com/en/rest/security-advisories/global-advisories

Returned advisories are converted to a CleanCVE-shaped dict compatible with
src.security.linking.compute_precise_matches: each advisory yields a CVE
record whose `configurations` field carries CPE-shaped entries derived from
the advisory's affected ranges, so the same precise-match path applies.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

GHSA_API_URL = "https://api.github.com/advisories"


def _parse_ghsa_range(range_text: str) -> dict[str, str]:
    """Convert a GHSA vulnerable_version_range into the NVD versionStart*/versionEnd* fields.

    GHSA range syntax (per https://docs.github.com/en/rest/security-advisories):
      - "= 1.2.3"          exact pin
      - ">= 1.2"           lower bound inclusive
      - "> 1.2"            lower bound exclusive
      - "<= 2.0"           upper bound inclusive
      - "< 2.0"            upper bound exclusive
      - ">= 1.2, < 2.0"    bounded range
    """
    out: dict[str, str] = {}
    if not range_text:
        return out
    for part in range_text.split(","):
        token = part.strip()
        m = re.match(r"^(>=|<=|>|<|=)\s*([0-9A-Za-z+_.\-]+)$", token)
        if not m:
            continue
        op, ver = m.group(1), m.group(2)
        if op == "=":
            out["versionStartIncluding"] = ver
            out["versionEndIncluding"] = ver
        elif op == ">=":
            out["versionStartIncluding"] = ver
        elif op == ">":
            out["versionStartExcluding"] = ver
        elif op == "<=":
            out["versionEndIncluding"] = ver
        elif op == "<":
            out["versionEndExcluding"] = ver
    return out


def _gha_to_clean_cve(adv: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a GHSA advisory JSON to a CleanCVE-shaped dict.

    Uses CVE id when assigned, falling back to GHSA id. Carries per-package
    affected ranges as cpe-shaped configurations so the existing precise-match
    path can consume them without a parallel implementation.
    """
    cve_id = (adv.get("cve_id") or adv.get("ghsa_id") or "").strip()
    if not cve_id:
        return None

    description = adv.get("summary") or adv.get("description") or ""
    severity = (adv.get("severity") or "UNKNOWN").upper()
    cvss = 0.0
    try:
        cvss = float((adv.get("cvss") or {}).get("score") or 0.0)
    except Exception:
        cvss = 0.0
    published = adv.get("published_at") or ""
    modified = adv.get("updated_at") or published

    nodes: list[dict[str, Any]] = []
    for vuln in adv.get("vulnerabilities", []) or []:
        pkg = (vuln.get("package") or {}) or {}
        name = pkg.get("name") or ""
        ecosystem = (pkg.get("ecosystem") or "").lower()
        if ecosystem != "maven":
            continue  # Only Maven advisories matter for this Java-only project.
        # Maven name is "group:artifact"
        if ":" not in name:
            continue
        group_id, artifact_id = name.split(":", 1)
        for r in vuln.get("vulnerable_version_range") or []:
            constraint = _parse_ghsa_range(r) if isinstance(r, str) else _parse_ghsa_range(r)
            if not constraint:
                continue
            nodes.append(
                {
                    "cpeMatch": [
                        {
                            "criteria": f"cpe:2.3:a:{group_id.lower()}:{artifact_id.lower()}:*:*:*:*:*:*:*:*",
                            **constraint,
                        }
                    ]
                }
            )
        # Some GHSA advisories give a single string range, not a list
        single_range = vuln.get("vulnerable_version_range")
        if isinstance(single_range, str) and single_range:
            constraint = _parse_ghsa_range(single_range)
            if constraint:
                nodes.append(
                    {
                        "cpeMatch": [
                            {
                                "criteria": f"cpe:2.3:a:{group_id.lower()}:{artifact_id.lower()}:*:*:*:*:*:*:*:*",
                                **constraint,
                            }
                        ]
                    }
                )

    if not nodes:
        return None

    return {
        "id": cve_id,
        "description": description,
        "cvss_score": cvss,
        "severity": severity,
        "published": published,
        "modified": modified,
        "configurations": [{"nodes": nodes}],
        "_source": "ghsa",
    }


def fetch_ghsa_advisories(
    deps: list[dict[str, Any]],
    api_token: str | None = None,
    timeout_s: int = 20,
) -> list[dict[str, Any]]:
    """Fetch GHSA advisories for a list of versioned Maven dependencies.

    Iterates per (group:artifact) -- the GitHub Advisory API supports
    filtering by package name. Returns CleanCVE-shaped dicts ready to feed
    into ``link_cves_to_dependencies``.
    """
    headers: dict[str, str] = {
        "User-Agent": "neo4j-code-graph/1.0",
        "Accept": "application/vnd.github+json",
    }
    token = api_token or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    seen_advisories: dict[str, dict[str, Any]] = {}
    queried: set[str] = set()

    for dep in deps:
        group_id = (dep.get("group_id") or "").strip()
        artifact_id = (dep.get("artifact_id") or "").strip()
        if not group_id or not artifact_id:
            continue
        affects = f"{group_id}:{artifact_id}"
        if affects in queried:
            continue
        queried.add(affects)
        try:
            resp = requests.get(
                GHSA_API_URL,
                params={"ecosystem": "maven", "affects": affects, "per_page": 100},
                headers=headers,
                timeout=timeout_s,
            )
        except Exception as e:
            logger.warning("GHSA fetch failed for %s: %s", affects, e)
            continue
        if resp.status_code == 403:
            logger.warning(
                "GHSA returned 403 for %s (rate-limited?); set GITHUB_TOKEN to raise the limit",
                affects,
            )
            continue
        if resp.status_code != 200:
            logger.warning(
                "GHSA returned %d for %s: %s", resp.status_code, affects, resp.text[:200]
            )
            continue
        try:
            advisories = resp.json() or []
        except Exception as e:
            logger.warning("GHSA returned non-JSON for %s: %s", affects, e)
            continue

        for adv in advisories:
            cve = _gha_to_clean_cve(adv)
            if cve is None:
                continue
            # Dedupe by CVE/GHSA id (an advisory may match multiple deps)
            seen_advisories.setdefault(cve["id"], cve)

    logger.info(
        "GHSA: fetched %d unique advisories across %d packages", len(seen_advisories), len(queried)
    )
    return list(seen_advisories.values())


__all__ = ["fetch_ghsa_advisories"]
