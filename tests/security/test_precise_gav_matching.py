#!/usr/bin/env python3
"""
Test cases for precise GAV-CVE matching.

These tests validate that CVE matching is accurate and prevents false positives
that could occur with loose string matching.
"""

import sys
from pathlib import Path

# Add src to Python path for testing
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from src.security.gav_cve_matcher import AffectedProduct, GAVCoordinate, PreciseGAVMatcher


class TestGAVCoordinate:
    """Test GAV coordinate handling."""

    def test_gav_coordinate_creation(self):
        """Test GAV coordinate creation and properties."""
        gav = GAVCoordinate("org.apache.commons", "commons-lang3", "3.12.0")

        assert gav.group_id == "org.apache.commons"
        assert gav.artifact_id == "commons-lang3"
        assert gav.version == "3.12.0"
        assert gav.full_coordinate == "org.apache.commons:commons-lang3:3.12.0"
        assert gav.package_key == "org.apache.commons:commons-lang3"

    def test_version_range_handling(self):
        """Test version range handling for GAVCoordinate."""
        gav1 = GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.14.1")

        # Test version ranges
        assert gav1.is_in_range("2.0.0", "2.15.0") is True  # boundary included
        assert gav1.is_in_range("2.14.1", "2.15.0") is True  # within range
        assert gav1.is_in_range("2.15.0", "2.15.0") is False  # boundary excluded

        # Test outside ranges
        assert gav1.is_in_range("1.9.0", "2.15.0") is True  # before range
        assert gav1.is_in_range("2.16.0", "2.15.0") is False  # after range
        assert gav1.is_in_range("3.0.0", "2.15.0") is False  # way after range


class TestVersionMatching:
    """Test version range matching logic."""

    def test_version_within_vulnerable_range(self):
        """Test that vulnerable versions are correctly identified."""
        affected = AffectedProduct(
            vendor="apache",
            product="log4j",
            version_start_including="2.0.0",
            version_end_excluding="2.15.0",
        )

        # Should match vulnerable versions
        assert affected.matches_version("2.14.1") is True
        assert affected.matches_version("2.10.0") is True
        assert affected.matches_version("2.0.0") is True

        # Should NOT match fixed versions
        assert affected.matches_version("2.15.0") is False
        assert affected.matches_version("2.17.0") is False
        assert affected.matches_version("1.9.0") is False

    def test_version_excluding_constraints(self):
        """Test version constraints with excluding boundaries."""
        affected = AffectedProduct(
            vendor="springframework",
            product="spring-core",
            version_start_excluding="5.0.0",
            version_end_including="5.3.21",
        )

        # Should match versions in range (excluding start)
        assert affected.matches_version("5.0.1") is True
        assert affected.matches_version("5.3.21") is True
        assert affected.matches_version("5.2.0") is True

        # Should NOT match boundary versions
        assert affected.matches_version("5.0.0") is False
        assert affected.matches_version("5.3.22") is False
        assert affected.matches_version("4.9.0") is False


class TestCVEMatching:
    """Test CVE to GAV matching logic."""

    @pytest.fixture
    def matcher(self):
        """Create matcher instance for testing."""
        return PreciseGAVMatcher()

    @pytest.fixture
    def log4j_cve_data(self):
        """Sample Log4j CVE data (CVE-2021-44228)."""
        return {
            "id": "CVE-2021-44228",
            "descriptions": [
                {"lang": "en", "value": "Apache Log4j2 2.0-beta9 through 2.15.0 JNDI features..."}
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

    @pytest.fixture
    def spring_cve_data(self):
        """Sample Spring CVE data."""
        return {
            "id": "CVE-2022-22965",
            "descriptions": [
                {"lang": "en", "value": "Spring Framework RCE via Data Binding on JDK 9+..."}
            ],
            "configurations": [
                {
                    "nodes": [
                        {
                            "cpeMatch": [
                                {
                                    "criteria": "cpe:2.3:a:vmware:spring_framework:*:*:*:*:*:*:*:*",
                                    "versionStartIncluding": "5.3.0",
                                    "versionEndExcluding": "5.3.18",
                                    "matchCriteriaId": "test-id-2",
                                }
                            ]
                        }
                    ]
                }
            ],
            "metrics": {
                "cvssMetricV31": [{"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]
            },
        }

    def test_exact_match_vulnerable_log4j(self, matcher, log4j_cve_data):
        """Test exact match for vulnerable Log4j version."""
        vulnerable_log4j = GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.14.1")

        confidence = matcher.match_gav_to_cve(vulnerable_log4j, log4j_cve_data)

        assert confidence == 1.0  # Exact match

    def test_no_match_fixed_log4j(self, matcher, log4j_cve_data):
        """Test no match for fixed Log4j version."""
        fixed_log4j = GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.17.0")

        confidence = matcher.match_gav_to_cve(fixed_log4j, log4j_cve_data)

        assert confidence is None  # No match for fixed version

    def test_no_false_positive_different_artifact(self, matcher, log4j_cve_data):
        """Test that different artifacts don't match incorrectly."""
        # Similar name but different artifact
        different_logger = GAVCoordinate("ch.qos.logback", "logback-classic", "1.2.3")

        confidence = matcher.match_gav_to_cve(different_logger, log4j_cve_data)

        assert confidence is None  # Should not match different logging library

    def test_spring_cve_matching(self, matcher, spring_cve_data):
        """Test Spring CVE matching."""
        vulnerable_spring = GAVCoordinate("org.springframework", "spring-core", "5.3.15")
        fixed_spring = GAVCoordinate("org.springframework", "spring-core", "5.3.18")

        # Vulnerable version should match
        vuln_confidence = matcher.match_gav_to_cve(vulnerable_spring, spring_cve_data)
        assert vuln_confidence == 1.0

        # Fixed version should not match
        fixed_confidence = matcher.match_gav_to_cve(fixed_spring, spring_cve_data)
        assert fixed_confidence is None


class TestFalsePositivePrevention:
    """Test cases specifically designed to prevent false positives."""

    @pytest.fixture
    def matcher(self):
        return PreciseGAVMatcher()

    def test_similar_names_no_false_match(self, matcher):
        """Test that similar library names don't create false matches."""
        # CVE for "commons-collections" should not match "commons-lang"
        commons_collections_cve = {
            "id": "CVE-2015-6420",
            "descriptions": [
                {"lang": "en", "value": "Apache Commons Collections deserialization vulnerability"}
            ],
            "configurations": [
                {
                    "nodes": [
                        {
                            "cpeMatch": [
                                {
                                    "criteria": (
                                        "cpe:2.3:a:apache:commons_collections:" "*:*:*:*:*:*:*:*"
                                    ),
                                    "versionEndExcluding": "3.2.2",
                                }
                            ]
                        }
                    ]
                }
            ],
        }

        # Should NOT match commons-lang3
        commons_lang = GAVCoordinate("org.apache.commons", "commons-lang3", "3.8.0")
        confidence = matcher.match_gav_to_cve(commons_lang, commons_collections_cve)

        assert confidence is None  # Should not match different Apache Commons library

    def test_version_boundary_precision(self, matcher):
        """Test precise version boundary handling."""
        boundary_cve = {
            "id": "CVE-TEST-BOUNDARY",
            "configurations": [
                {
                    "nodes": [
                        {
                            "cpeMatch": [
                                {
                                    "criteria": "cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*",
                                    "versionStartIncluding": "2.0.0",
                                    "versionEndExcluding": "2.15.0",
                                }
                            ]
                        }
                    ]
                }
            ],
        }

        log4j_boundary = GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.15.0")
        confidence = matcher.match_gav_to_cve(log4j_boundary, boundary_cve)

        # Version 2.15.0 should NOT match (excluded boundary)
        assert confidence is None

    def test_generic_names_require_group_validation(self, matcher):
        """Test that generic artifact names require group validation."""
        generic_cve = {
            "id": "CVE-TEST-GENERIC",
            "configurations": [
                {
                    "nodes": [
                        {
                            "cpeMatch": [
                                {
                                    "criteria": "cpe:2.3:a:example:core:*:*:*:*:*:*:*:*",
                                    "versionEndExcluding": "1.0.0",
                                }
                            ]
                        }
                    ]
                }
            ],
        }

        # Generic name "core" should require additional validation
        generic_core = GAVCoordinate("com.unrelated", "core", "0.9.0")
        confidence = matcher.match_gav_to_cve(generic_core, generic_cve)

        # Should not match due to conservative fuzzy matching
        assert confidence is None or confidence < 1.0


class TestIntegrationScenarios:
    """Integration test scenarios with realistic data."""

    @pytest.fixture
    def matcher(self):
        return PreciseGAVMatcher()

    def test_real_world_dependency_list(self, matcher):
        """Test with realistic dependency list."""
        dependencies = [
            GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.14.1"),
            GAVCoordinate("org.springframework", "spring-core", "5.3.15"),
            GAVCoordinate("com.fasterxml.jackson.core", "jackson-databind", "2.12.6"),
            GAVCoordinate("junit", "junit", "4.13.2"),
            GAVCoordinate("org.apache.commons", "commons-lang3", "3.12.0"),
        ]

        # Mock CVE data
        cve_list = [
            {
                "id": "CVE-2021-44228",  # Log4j
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        "criteria": "cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*",
                                        "versionStartIncluding": "2.0",
                                        "versionEndExcluding": "2.15.0",
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
        ]

        matches = matcher.validate_dependencies_against_cves(dependencies, cve_list)

        # Should only match Log4j, not other dependencies
        assert len(matches) == 1
        matched_dep, matched_cve, confidence = matches[0]
        assert matched_dep.artifact_id == "log4j-core"
        assert matched_cve.cve_id == "CVE-2021-44228"
        assert confidence == 1.0


def test_compare_with_old_matching():
    """Compare new precise matching with old loose matching."""
    # This would be a test to show how the old system would create false positives
    # while the new system correctly avoids them

    # Example: CVE mentioning "spring" should not match "spring-boot"
    # if it's specifically about "spring-framework"
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
