#!/usr/bin/env python3
"""
Demonstration of precise GAV-based CVE matching vs loose text matching.

This script shows how the enhanced CVE matching prevents false positives
that would occur with the old text-based matching approach.
"""

import logging
import sys

from src.security.gav_cve_matcher import GAVCoordinate, PreciseGAVMatcher
from src.utils.common import setup_logging

logger = logging.getLogger(__name__)


def demonstrate_old_vs_new_matching():
    """Demonstrate the difference between old loose matching and new precise matching."""
    logger.info("🔍 CVE Matching Accuracy Demonstration")
    logger.info("%s", "=" * 60)

    # Create test dependencies
    test_dependencies = [
        GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.14.1"),  # Vulnerable
        GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.17.0"),  # Fixed
        GAVCoordinate("ch.qos.logback", "logback-classic", "1.2.3"),  # Different logger
        GAVCoordinate("org.apache.commons", "commons-lang3", "3.8.0"),  # Different Apache project
        GAVCoordinate(
            "org.apache.commons", "commons-collections4", "4.1"
        ),  # Different Commons library
        GAVCoordinate("org.springframework", "spring-core", "5.3.15"),  # Vulnerable Spring
        GAVCoordinate("org.springframework", "spring-boot", "2.6.0"),  # Different Spring project
    ]

    # Sample CVE data for Log4j (CVE-2021-44228)
    log4j_cve = {
        "id": "CVE-2021-44228",
        "descriptions": [
            {
                "lang": "en",
                "value": (
                    "Apache Log4j2 2.0-beta9 through 2.15.0 JNDI features used in configuration, "
                    "log messages, and parameters do not protect against attacker controlled "
                    "LDAP and other JNDI related endpoints."
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

    # Sample CVE data that mentions "apache" but is for a different project
    apache_cve_different = {
        "id": "CVE-2015-6420",
        "descriptions": [
            {
                "lang": "en",
                "value": (
                    "Serialization vulnerability in Apache Commons Collections library before 3.2.2"
                ),
            }
        ],
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "criteria": "cpe:2.3:a:apache:commons_collections:*:*:*:*:*:*:*:*",
                                "versionEndExcluding": "3.2.2",
                            }
                        ]
                    }
                ]
            }
        ],
    }

    # Test with enhanced matcher
    logger.info("\n🎯 Enhanced Precise GAV Matching Results:")
    logger.info("%s", "-" * 40)

    matcher = PreciseGAVMatcher()

    for dep in test_dependencies:
        # Test against Log4j CVE
        log4j_confidence = matcher.match_gav_to_cve(dep, log4j_cve)
        collections_confidence = matcher.match_gav_to_cve(dep, apache_cve_different)

        logger.info("\n📦 %s", dep.full_coordinate)

        if log4j_confidence:
            logger.info("   ✅ MATCHES CVE-2021-44228 (confidence: %s)", log4j_confidence)
        else:
            logger.info("   ⚪ No match for CVE-2021-44228")

        if collections_confidence:
            logger.info("   ✅ MATCHES CVE-2015-6420 (confidence: %s)", collections_confidence)
        else:
            logger.info("   ⚪ No match for CVE-2015-6420")

    # Simulate old loose matching
    logger.info("\n%s", "=" * 60)
    logger.info("🚨 Old Loose Text Matching (PROBLEMATIC):")
    logger.info("%s", "-" * 40)

    def simulate_old_matching(dep_name: str, cve_description: str) -> bool:
        """Simulate the old problematic text matching approach."""
        dep_lower = dep_name.lower()
        desc_lower = cve_description.lower()

        # Old approach: simple substring matching
        if "apache" in dep_lower and "apache" in desc_lower:
            return True
        if "log" in dep_lower and "log" in desc_lower:
            return True
        if "spring" in dep_lower and "spring" in desc_lower:
            return True

        return False

    for dep in test_dependencies:
        log4j_match = simulate_old_matching(
            dep.full_coordinate, log4j_cve["descriptions"][0]["value"]
        )
        collections_match = simulate_old_matching(
            dep.full_coordinate, apache_cve_different["descriptions"][0]["value"]
        )

        logger.info("\n📦 %s", dep.full_coordinate)

        if log4j_match:
            status = "❌ FALSE POSITIVE" if dep.artifact_id != "log4j-core" else "✅ Correct match"
            logger.info("   %s - matches CVE-2021-44228", status)
        else:
            logger.info("   ⚪ No match for CVE-2021-44228")

        if collections_match:
            status = (
                "❌ FALSE POSITIVE"
                if "commons-collections" not in dep.artifact_id
                else "✅ Correct match"
            )
            logger.info("   %s - matches CVE-2015-6420", status)
        else:
            logger.info("   ⚪ No match for CVE-2015-6420")

    logger.info("\n%s", "=" * 60)
    logger.info("📊 Summary of Improvements:")
    logger.info("%s", "-" * 40)
    logger.info("✅ Enhanced matching uses:")
    logger.info("   • Exact GAV coordinate matching")
    logger.info("   • CPE (Common Platform Enumeration) data")
    logger.info("   • Precise version range checking")
    logger.info("   • Conservative fuzzy matching with validation")
    logger.info("")
    logger.info("❌ Old matching problems:")
    logger.info("   • Simple text substring matching")
    logger.info("   • No version awareness")
    logger.info("   • High false positive rate")
    logger.info("   • Matches unrelated Apache projects")


def test_version_precision():
    """Test precision of version range matching."""
    logger.info("\n🎯 Version Range Precision Test:")
    logger.info("%s", "-" * 40)

    # Test CVE with specific version range
    version_cve = {
        "id": "CVE-TEST-VERSION",
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

    test_versions = [
        ("2.14.1", "VULNERABLE - within range"),
        ("2.15.0", "SAFE - boundary excluded"),
        ("2.17.0", "SAFE - newer version"),
        ("1.9.0", "SAFE - older version"),
        ("2.0.0", "VULNERABLE - boundary included"),
    ]

    matcher = PreciseGAVMatcher()

    for version, expected in test_versions:
        gav = GAVCoordinate("org.apache.logging.log4j", "log4j-core", version)
        confidence = matcher.match_gav_to_cve(gav, version_cve)

        if confidence:
            result = f"✅ VULNERABLE (confidence: {confidence})"
        else:
            result = "✅ SAFE"

        logger.info("   log4j-core:%s -> %s (%s)", version, result, expected)


def main():
    """Main demonstration function."""
    setup_logging("INFO")
    logger.info("🔬 Neo4j Code Graph - CVE Matching Accuracy Demo")
    logger.info("This demo shows why precise GAV matching is critical for security analysis")

    try:
        demonstrate_old_vs_new_matching()
        test_version_precision()

        logger.info("\n%s", "=" * 60)
        logger.info("🎉 Demo completed!")
        logger.info("")
        logger.info("📝 Next Steps:")
        logger.info("1. Run tests: pytest tests/security/test_precise_gav_matching.py -v")
        logger.info("2. Integrate enhanced matching into CVE analysis pipeline")
        logger.info("3. Update dependency extraction to use proper GAV coordinates")

    except Exception as e:
        logger.error(f"Demo failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
