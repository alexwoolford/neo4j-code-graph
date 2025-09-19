#!/usr/bin/env python3
"""
Precise GAV-based CVE matching for Java dependencies.

This module implements accurate CVE matching using:
1. Full GAV (Group:Artifact:Version) coordinates
2. CPE (Common Platform Enumeration) matching
3. Version range checking
4. Structured vulnerability data
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from packaging.version import Version

try:
    from src.security.types import CleanCVE  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from security.types import CleanCVE  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class GAVCoordinate:
    """Maven GAV (Group, Artifact, Version) coordinate."""

    group_id: str
    artifact_id: str
    version: str

    @property
    def full_coordinate(self) -> str:
        """Return full GAV coordinate string."""
        return f"{self.group_id}:{self.artifact_id}:{self.version}"

    @property
    def package_key(self) -> str:
        """Return package key for matching (group:artifact)."""
        return f"{self.group_id}:{self.artifact_id}"

    def is_in_range(self, start: str, end: str) -> bool:
        """Return ``True`` if ``version`` is within ``[start, end)``."""
        try:
            start_v = Version(start)
            end_v = Version(end)
            if start_v > end_v:
                start_v, end_v = end_v, start_v
            current = Version(self.version)
            return start_v <= current < end_v
        except Exception as e:  # pragma: no cover - invalid version strings
            logger.warning("Version comparison failed for %s: %s", self.version, e)
            return False


@dataclass
class CVEVulnerability:
    """Structured CVE vulnerability data."""

    cve_id: str
    description: str
    cvss_score: float
    severity: str
    published_date: str
    affected_products: list["AffectedProduct"]


@dataclass
class AffectedProduct:
    """Product affected by a CVE with version constraints."""

    vendor: str
    product: str
    version_start_including: str | None = None
    version_start_excluding: str | None = None
    version_end_including: str | None = None
    version_end_excluding: str | None = None

    @staticmethod
    def _clean_version_string(raw: str | None) -> str | None:
        """Sanitize occasionally malformed NVD version strings.

        Examples fixed:
        - "2.0.0."  -> "2.0.0"
        - " 2.13.4 " -> "2.13.4"
        - "v2.12.0"  -> "2.12.0"
        - "2_12_0"   -> "2.12.0"
        """
        if raw is None:
            return None
        v = raw.strip().strip("'\"")
        v = v.replace("_", ".")
        if v.startswith("v") and len(v) > 1 and v[1].isdigit():
            v = v[1:]
        v = re.sub(r"[^0-9A-Za-z.+-]+$", "", v)
        return v or None

    def matches_version(self, target_version: str) -> bool:
        """Check if target version falls within vulnerable range."""
        try:
            target_ver = Version(target_version)

            # Check start constraints
            vsi = self._clean_version_string(self.version_start_including)
            if vsi:
                try:
                    if target_ver < Version(vsi):
                        return False
                except Exception as e:
                    logger.debug("Ignoring invalid version_start_including '%s': %s", vsi, e)
            vse = self._clean_version_string(self.version_start_excluding)
            if vse:
                try:
                    if target_ver <= Version(vse):
                        return False
                except Exception as e:
                    logger.debug("Ignoring invalid version_start_excluding '%s': %s", vse, e)

            # Check end constraints
            vei = self._clean_version_string(self.version_end_including)
            if vei:
                try:
                    if target_ver > Version(vei):
                        return False
                except Exception as e:
                    logger.debug("Ignoring invalid version_end_including '%s': %s", vei, e)
            vee = self._clean_version_string(self.version_end_excluding)
            if vee:
                try:
                    if target_ver >= Version(vee):
                        return False
                except Exception as e:
                    logger.debug("Ignoring invalid version_end_excluding '%s': %s", vee, e)

            return True

        except Exception as e:
            logger.warning(f"Version comparison failed for {target_version}: {e}")
            return False


class PreciseGAVMatcher:
    """Precise CVE matching using GAV coordinates and CPE data."""

    def __init__(self):
        self.cpe_patterns = self._load_known_cpe_patterns()

    @staticmethod
    def _load_known_cpe_patterns() -> dict[str, str]:
        """Load known GAV to CPE mappings."""
        return {
            # Apache Commons
            "org.apache.commons:commons-lang3": "apache:commons_lang",
            "org.apache.commons:commons-collections4": "apache:commons_collections",
            # Spring Framework
            "org.springframework:spring-core": "vmware:spring_framework",
            "org.springframework:spring-boot": "vmware:spring_boot",
            "org.springframework.security:spring-security-core": "vmware:spring_security",
            # Jackson
            "com.fasterxml.jackson.core:jackson-core": "fasterxml:jackson-core",
            "com.fasterxml.jackson.core:jackson-databind": "fasterxml:jackson-databind",
            # Log4j
            "org.apache.logging.log4j:log4j-core": "apache:log4j",
            # JUnit
            "junit:junit": "junit:junit",
            "org.junit.jupiter:junit-jupiter": "junit:junit5",
            # Add more as needed
        }

    @staticmethod
    def extract_cpe_from_cve(cve_data: Mapping[str, Any]) -> list[tuple[str, AffectedProduct]]:
        """Extract CPE matches and version constraints from CVE data."""
        affected_products: list[tuple[str, AffectedProduct]] = []

        configs_raw = cve_data.get("configurations")
        if not configs_raw:
            return affected_products

        # NVD 2.0 provides configurations as an object with nodes; normalize to list
        if isinstance(configs_raw, dict):
            configs = [configs_raw]
        elif isinstance(configs_raw, list):
            configs = configs_raw
        else:
            configs = []

        for config in configs:
            for node in config.get("nodes", []) if isinstance(config, dict) else []:
                for cpe_match in node.get("cpeMatch", []):
                    cpe_uri = cpe_match.get("criteria", "")

                    # Parse CPE URI: cpe:2.3:a:vendor:product:version:...
                    cpe_parts = cpe_uri.split(":")
                    if len(cpe_parts) >= 5 and cpe_parts[0] == "cpe":
                        vendor = cpe_parts[3]
                        product = cpe_parts[4]

                        # Extract version constraints
                        affected_product = AffectedProduct(
                            vendor=vendor,
                            product=product,
                            version_start_including=cpe_match.get("versionStartIncluding"),
                            version_start_excluding=cpe_match.get("versionStartExcluding"),
                            version_end_including=cpe_match.get("versionEndIncluding"),
                            version_end_excluding=cpe_match.get("versionEndExcluding"),
                        )

                        affected_products.append((cpe_uri, affected_product))

        return affected_products

    def match_gav_to_cve(self, gav: GAVCoordinate, cve_data: Mapping[str, Any]) -> float | None:
        """
        Match GAV coordinate to CVE with confidence score.

        Returns:
            Confidence score (0.0-1.0) if match found, None otherwise
        """
        # Check if we have a known CPE pattern for this GAV
        package_key = gav.package_key
        if package_key not in self.cpe_patterns:
            # Try fuzzy CPE matching for unknown packages
            return self._fuzzy_cpe_match(gav, cve_data)

        expected_cpe_pattern = self.cpe_patterns[package_key]
        cpe_matches = PreciseGAVMatcher.extract_cpe_from_cve(cve_data)

        def _norm(s: str) -> str:
            return s.lower().replace("-", "").replace("_", "")

        exp_norm = _norm(expected_cpe_pattern)

        for cpe_uri, affected_product in cpe_matches:
            # Check if CPE matches our expected pattern (normalize '-' vs '_')
            if exp_norm in _norm(cpe_uri):
                # Require version constraints in the CVE; reject versionless CVEs
                has_any_version_constraint = any(
                    [
                        affected_product.version_start_including,
                        affected_product.version_start_excluding,
                        affected_product.version_end_including,
                        affected_product.version_end_excluding,
                    ]
                )
                if not has_any_version_constraint:
                    continue
                # Check version constraints precisely
                if affected_product.matches_version(gav.version):
                    return 1.0  # Exact match with version constraint

        return None

    @staticmethod
    def _fuzzy_cpe_match(gav: GAVCoordinate, cve_data: Mapping[str, Any]) -> float | None:
        """Fuzzy matching for unknown packages - much more conservative."""
        cpe_matches = PreciseGAVMatcher.extract_cpe_from_cve(cve_data)

        # Extract meaningful parts from GAV
        artifact_lower = gav.artifact_id.lower()
        group_parts = gav.group_id.lower().split(".")

        for cpe_uri, affected_product in cpe_matches:
            cpe_lower = cpe_uri.lower()

            # Very conservative matching
            # Only match if artifact name appears in CPE AND it's not too generic
            if (
                len(artifact_lower) > 4
                and artifact_lower in cpe_lower
                and artifact_lower not in ["core", "common", "utils", "base"]
            ):
                # Additional validation - check if group parts match
                group_matches = sum(
                    1 for part in group_parts if len(part) > 3 and part in cpe_lower
                )

                has_any_version_constraint = any(
                    [
                        affected_product.version_start_including,
                        affected_product.version_start_excluding,
                        affected_product.version_end_including,
                        affected_product.version_end_excluding,
                    ]
                )
                if (
                    group_matches > 0
                    and has_any_version_constraint
                    and affected_product.matches_version(gav.version)
                ):
                    # Lower confidence for fuzzy match
                    return 0.7

        return None

    def validate_dependencies_against_cves(
        self, dependencies: list[GAVCoordinate], cve_list: list[CleanCVE]
    ) -> list[tuple[GAVCoordinate, CVEVulnerability, float]]:
        """
        Validate list of dependencies against CVE database.

        Returns:
            List of (dependency, cve, confidence_score) tuples for matches
        """
        matches: list[tuple[GAVCoordinate, CVEVulnerability, float]] = []

        for dep in dependencies:
            for cve_data in cve_list:
                confidence = self.match_gav_to_cve(dep, cve_data)
                if confidence is not None:
                    # Convert CVE data to structured format
                    affected_products = [ap for _, ap in self.extract_cpe_from_cve(cve_data)]

                    cve = CVEVulnerability(
                        cve_id=cve_data.get("id", ""),
                        description=self._extract_description(cve_data),
                        cvss_score=self._extract_cvss_score(cve_data),
                        severity=self._extract_severity(cve_data),
                        published_date=cve_data.get("published", ""),
                        affected_products=affected_products,
                    )

                    matches.append((dep, cve, confidence))

        return matches

    @staticmethod
    def _extract_description(cve_data: Mapping[str, Any]) -> str:
        """Extract English description from CVE data."""
        if "descriptions" in cve_data:
            for desc in cve_data["descriptions"]:
                if desc.get("lang") == "en":
                    return desc.get("value", "")
        return cve_data.get("description", "")

    @staticmethod
    def _extract_cvss_score(cve_data: Mapping[str, Any]) -> float:
        """Extract CVSS score from CVE data."""
        metrics = cve_data.get("metrics", {})

        # Try CVSS v3 first
        for version_key in ["cvssMetricV31", "cvssMetricV30"]:
            if version_key in metrics:
                for metric in metrics[version_key]:
                    cvss_data = metric.get("cvssData", {})
                    if "baseScore" in cvss_data:
                        return float(cvss_data["baseScore"])

        # Fallback to v2
        if "cvssMetricV2" in metrics:
            for metric in metrics["cvssMetricV2"]:
                cvss_data = metric.get("cvssData", {})
                if "baseScore" in cvss_data:
                    return float(cvss_data["baseScore"])

        return 0.0

    @staticmethod
    def _extract_severity(cve_data: Mapping[str, Any]) -> str:
        """Extract severity from CVE data."""
        cvss_score = PreciseGAVMatcher._extract_cvss_score(cve_data)

        if cvss_score >= 9.0:
            return "CRITICAL"
        elif cvss_score >= 7.0:
            return "HIGH"
        elif cvss_score >= 4.0:
            return "MEDIUM"
        elif cvss_score > 0.0:
            return "LOW"
        else:
            return "NONE"


# Test data and validation functions
def create_test_dependencies() -> list[GAVCoordinate]:
    """Create test dependencies with known vulnerabilities."""
    return [
        GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.14.1"),  # Vulnerable
        GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.17.0"),  # Fixed
        GAVCoordinate("org.springframework", "spring-core", "5.3.18"),  # May be vulnerable
        GAVCoordinate("com.fasterxml.jackson.core", "jackson-databind", "2.12.6"),  # Check
        GAVCoordinate("junit", "junit", "4.13.2"),  # Safe
    ]


def run_validation_tests():
    """Run validation tests with known CVE data."""
    logger.info("🧪 Running GAV-CVE matching validation tests...")

    matcher = PreciseGAVMatcher()
    test_deps = create_test_dependencies()

    # Test with sample CVE data (would come from real NVD API)
    sample_cve = {
        "id": "CVE-2021-44228",
        "descriptions": [
            {
                "lang": "en",
                "value": (
                    "Apache Log4j2 2.0-beta9 through 2.15.0 "
                    "(excluding security releases 2.12.2, 2.12.3, and 2.3.1) "
                    "JNDI features..."
                ),
            }
        ],
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "criteria": "cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*",
                                "versionStartIncluding": "2.0",
                                "versionEndExcluding": "2.15.0",
                                "matchCriteriaId": "test-id",
                            }
                        ]
                    }
                ]
            }
        ],
        "metrics": {
            "cvssMetricV31": [{"cvssData": {"baseScore": 10.0, "baseSeverity": "CRITICAL"}}]
        },
    }

    # Test matching
    for dep in test_deps:
        confidence = matcher.match_gav_to_cve(dep, sample_cve)
        if confidence:
            logger.info(
                f"✅ MATCH: {dep.full_coordinate} -> CVE-2021-44228 (confidence: {confidence})"
            )
        else:
            logger.info(f"⚪ NO MATCH: {dep.full_coordinate}")
