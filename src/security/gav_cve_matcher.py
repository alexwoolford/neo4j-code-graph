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
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from packaging.version import Version

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

    def is_in_range(self, start_version: str, end_version: str) -> bool:
        """Check if this coordinate's version falls within [start, end)."""
        try:
            current = Version(self.version)
            return Version(start_version) <= current < Version(end_version)
        except Exception:
            return False


@dataclass
class CVEVulnerability:
    """Structured CVE vulnerability data."""

    cve_id: str
    description: str
    cvss_score: float
    severity: str
    published_date: str
    affected_products: List["AffectedProduct"]


@dataclass
class AffectedProduct:
    """Product affected by a CVE with version constraints."""

    vendor: str
    product: str
    version_start_including: Optional[str] = None
    version_start_excluding: Optional[str] = None
    version_end_including: Optional[str] = None
    version_end_excluding: Optional[str] = None

    def matches_version(self, target_version: str) -> bool:
        """Check if target version falls within vulnerable range."""
        try:
            target_ver = Version(target_version)

            # Check start constraints
            if self.version_start_including:
                if target_ver < Version(self.version_start_including):
                    return False

            if self.version_start_excluding:
                if target_ver <= Version(self.version_start_excluding):
                    return False

            # Check end constraints
            if self.version_end_including:
                if target_ver > Version(self.version_end_including):
                    return False

            if self.version_end_excluding:
                if target_ver >= Version(self.version_end_excluding):
                    return False

            return True

        except Exception as e:
            logger.warning(f"Version comparison failed for {target_version}: {e}")
            return False


class PreciseGAVMatcher:
    """Precise CVE matching using GAV coordinates and CPE data."""

    def __init__(self):
        self.cpe_patterns = self._load_known_cpe_patterns()

    def _load_known_cpe_patterns(self) -> Dict[str, str]:
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

    def extract_cpe_from_cve(self, cve_data: Dict) -> List[Tuple[str, AffectedProduct]]:
        """Extract CPE matches and version constraints from CVE data."""
        affected_products = []

        if "configurations" not in cve_data:
            return affected_products

        for config in cve_data["configurations"]:
            for node in config.get("nodes", []):
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

    def match_gav_to_cve(self, gav: GAVCoordinate, cve_data: Dict) -> Optional[float]:
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
        cpe_matches = self.extract_cpe_from_cve(cve_data)

        for cpe_uri, affected_product in cpe_matches:
            # Check if CPE matches our expected pattern
            if expected_cpe_pattern in cpe_uri.lower():
                # Check version constraints
                if affected_product.matches_version(gav.version):
                    return 1.0  # Exact match with version constraint

        return None

    def _fuzzy_cpe_match(self, gav: GAVCoordinate, cve_data: Dict) -> Optional[float]:
        """Fuzzy matching for unknown packages - much more conservative."""
        cpe_matches = self.extract_cpe_from_cve(cve_data)

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

                if group_matches > 0 and affected_product.matches_version(gav.version):
                    # Lower confidence for fuzzy match
                    return 0.7

        return None

    def validate_dependencies_against_cves(
        self, dependencies: List[GAVCoordinate], cve_list: List[Dict]
    ) -> List[Tuple[GAVCoordinate, CVEVulnerability, float]]:
        """
        Validate list of dependencies against CVE database.

        Returns:
            List of (dependency, cve, confidence_score) tuples for matches
        """
        matches = []

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

    def _extract_description(self, cve_data: Dict) -> str:
        """Extract English description from CVE data."""
        if "descriptions" in cve_data:
            for desc in cve_data["descriptions"]:
                if desc.get("lang") == "en":
                    return desc.get("value", "")
        return cve_data.get("description", "")

    def _extract_cvss_score(self, cve_data: Dict) -> float:
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

    def _extract_severity(self, cve_data: Dict) -> str:
        """Extract severity from CVE data."""
        cvss_score = self._extract_cvss_score(cve_data)

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
def create_test_dependencies() -> List[GAVCoordinate]:
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
                "value": "Apache Log4j2 2.0-beta9 through 2.15.0 (excluding security releases 2.12.2, 2.12.3, and 2.3.1) JNDI features...",
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_validation_tests()
