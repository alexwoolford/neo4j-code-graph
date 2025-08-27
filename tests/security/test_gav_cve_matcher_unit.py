from __future__ import annotations

import pytest

from src.security.gav_cve_matcher import (
    AffectedProduct,
    GAVCoordinate,
    PreciseGAVMatcher,
)


def _sample_log4j_cve() -> dict:
    return {
        "id": "CVE-2021-44228",
        "descriptions": [{"lang": "en", "value": "Log4Shell"}],
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
        "metrics": {
            "cvssMetricV31": [{"cvssData": {"baseScore": 10.0, "baseSeverity": "CRITICAL"}}]
        },
    }


def test_gav_coordinate_properties():
    gav = GAVCoordinate("org.apache", "lib", "1.2.3")
    assert gav.full_coordinate == "org.apache:lib:1.2.3"
    assert gav.package_key == "org.apache:lib"
    # in-range inclusive lower, exclusive upper
    assert gav.is_in_range("1.0.0", "2.0.0") is True
    assert gav.is_in_range("1.2.3", "1.2.3") is False


@pytest.mark.parametrize(
    "constraints, target, expected",
    [
        ({"versionStartIncluding": "1.0.0", "versionEndExcluding": "2.0.0"}, "1.5.0", True),
        ({"versionStartExcluding": "1.0.0", "versionEndIncluding": "2.0.0"}, "1.0.0", False),
        ({"versionStartExcluding": "1.0.0", "versionEndIncluding": "2.0.0"}, "2.0.0", True),
        ({"versionStartIncluding": "1.0.0"}, "0.9.9", False),
        ({"versionEndExcluding": "1.2.0"}, "1.2.0", False),
    ],
)
def test_affected_product_matches_version(constraints, target, expected):
    ap = AffectedProduct(
        vendor="apache",
        product="lib",
        version_start_including=constraints.get("versionStartIncluding"),
        version_start_excluding=constraints.get("versionStartExcluding"),
        version_end_including=constraints.get("versionEndIncluding"),
        version_end_excluding=constraints.get("versionEndExcluding"),
    )
    assert ap.matches_version(target) is expected


def test_extract_cpe_from_cve_parses_constraints():
    matcher = PreciseGAVMatcher()
    cpe_list = matcher.extract_cpe_from_cve(_sample_log4j_cve())
    assert len(cpe_list) == 1
    cpe_uri, ap = cpe_list[0]
    assert cpe_uri.startswith("cpe:2.3:a:apache:log4j:")
    assert ap.version_start_including == "2.0"
    assert ap.version_end_excluding == "2.15.0"


def test_match_gav_to_cve_exact_match_with_constraints():
    matcher = PreciseGAVMatcher()
    # Known mapping exists for log4j-core -> apache:log4j
    gav = GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.14.1")
    confidence = matcher.match_gav_to_cve(gav, _sample_log4j_cve())
    assert confidence == 1.0


def test_match_gav_to_cve_respects_version_constraints():
    matcher = PreciseGAVMatcher()
    gav_fixed = GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.17.0")
    assert matcher.match_gav_to_cve(gav_fixed, _sample_log4j_cve()) is None


def test_fuzzy_cpe_match_conservative():
    matcher = PreciseGAVMatcher()
    # Artifact appears in CPE but group parts must also match; ensure version constraints respected
    cve = {
        "id": "TEST-1",
        "descriptions": [{"lang": "en", "value": "test"}],
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "criteria": "cpe:2.3:a:vendor:myartifact:*:*:*:*:*:*:*:*",
                                "versionStartIncluding": "1.0.0",
                                "versionEndExcluding": "2.0.0",
                            }
                        ]
                    }
                ]
            }
        ],
    }
    # Group shares "vendor" token; artifact "myartifact" appears in CPE
    gav = GAVCoordinate("com.vendor.platform", "myartifact", "1.5.0")
    assert matcher.match_gav_to_cve(gav, cve) == pytest.approx(0.7)
