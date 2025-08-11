#!/usr/bin/env python3
"""
Demonstration of precise GAV-based CVE matching vs loose text matching.

This script shows how the enhanced CVE matching prevents false positives
that would occur with the old text-based matching approach.
"""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from security.gav_cve_matcher import GAVCoordinate, PreciseGAVMatcher

logger = logging.getLogger(__name__)


def demonstrate_old_vs_new_matching():
    """Demonstrate the difference between old loose matching and new precise matching."""
    print("🔍 CVE Matching Accuracy Demonstration")
    print("=" * 60)

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
    print("\n🎯 Enhanced Precise GAV Matching Results:")
    print("-" * 40)

    matcher = PreciseGAVMatcher()

    for dep in test_dependencies:
        # Test against Log4j CVE
        log4j_confidence = matcher.match_gav_to_cve(dep, log4j_cve)
        collections_confidence = matcher.match_gav_to_cve(dep, apache_cve_different)

        print(f"\n📦 {dep.full_coordinate}")

        if log4j_confidence:
            print(f"   ✅ MATCHES CVE-2021-44228 (confidence: {log4j_confidence})")
        else:
            print("   ⚪ No match for CVE-2021-44228")

        if collections_confidence:
            print(f"   ✅ MATCHES CVE-2015-6420 (confidence: {collections_confidence})")
        else:
            print("   ⚪ No match for CVE-2015-6420")

    # Simulate old loose matching
    print("\n" + "=" * 60)
    print("🚨 Old Loose Text Matching (PROBLEMATIC):")
    print("-" * 40)

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

        print(f"\n📦 {dep.full_coordinate}")

        if log4j_match:
            status = "❌ FALSE POSITIVE" if dep.artifact_id != "log4j-core" else "✅ Correct match"
            print(f"   {status} - matches CVE-2021-44228")
        else:
            print("   ⚪ No match for CVE-2021-44228")

        if collections_match:
            status = (
                "❌ FALSE POSITIVE"
                if "commons-collections" not in dep.artifact_id
                else "✅ Correct match"
            )
            print(f"   {status} - matches CVE-2015-6420")
        else:
            print("   ⚪ No match for CVE-2015-6420")

    print("\n" + "=" * 60)
    print("📊 Summary of Improvements:")
    print("-" * 40)
    print("✅ Enhanced matching uses:")
    print("   • Exact GAV coordinate matching")
    print("   • CPE (Common Platform Enumeration) data")
    print("   • Precise version range checking")
    print("   • Conservative fuzzy matching with validation")
    print()
    print("❌ Old matching problems:")
    print("   • Simple text substring matching")
    print("   • No version awareness")
    print("   • High false positive rate")
    print("   • Matches unrelated Apache projects")


def test_version_precision():
    """Test precision of version range matching."""
    print("\n🎯 Version Range Precision Test:")
    print("-" * 40)

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

        print(f"   log4j-core:{version} -> {result} ({expected})")


def main():
    """Main demonstration function."""
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from utils.common import setup_logging

    setup_logging("INFO")

    print("🔬 Neo4j Code Graph - CVE Matching Accuracy Demo")
    print("This demo shows why precise GAV matching is critical for security analysis")

    try:
        demonstrate_old_vs_new_matching()
        test_version_precision()

        print("\n" + "=" * 60)
        print("🎉 Demo completed!")
        print()
        print("📝 Next Steps:")
        print("1. Run tests: pytest tests/security/test_precise_gav_matching.py -v")
        print("2. Integrate enhanced matching into CVE analysis pipeline")
        print("3. Update dependency extraction to use proper GAV coordinates")

    except Exception as e:
        logger.error(f"Demo failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
