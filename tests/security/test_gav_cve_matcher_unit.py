#!/usr/bin/env python3

from __future__ import annotations


def test_affected_product_version_matching_variants():
    from src.security.gav_cve_matcher import AffectedProduct

    ap = AffectedProduct(
        vendor="apache",
        product="log4j",
        version_start_including="2.0",
        version_end_excluding="2.10.0",
    )
    assert ap.matches_version("2.0") is True
    assert ap.matches_version("2.5.0") is True
    assert ap.matches_version("2.10.0") is False

    ap2 = AffectedProduct(
        vendor="acme",
        product="lib",
        version_start_excluding="1.0",
        version_end_including="1.5",
    )
    assert ap2.matches_version("1.0") is False
    assert ap2.matches_version("1.2") is True
    assert ap2.matches_version("1.5") is True


def test_extract_cpe_from_cve_minimal_and_match():
    from src.security.gav_cve_matcher import PreciseGAVMatcher

    matcher = PreciseGAVMatcher()
    cve = {
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "criteria": "cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*",
                                "versionStartIncluding": "2.0",
                                "versionEndExcluding": "2.10.0",
                            }
                        ]
                    }
                ]
            }
        ]
    }
    rows = matcher.extract_cpe_from_cve(cve)
    assert rows and rows[0][0].startswith("cpe:2.3:a:apache:log4j")


def test_match_gav_to_cve_exact_and_fuzzy_and_negative():
    from src.security.gav_cve_matcher import GAVCoordinate, PreciseGAVMatcher

    matcher = PreciseGAVMatcher()
    cve = {
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
        ]
    }
    # Exact known pattern
    gav = GAVCoordinate("org.apache.logging.log4j", "log4j-core", "2.14.1")
    conf = matcher.match_gav_to_cve(gav, cve)
    assert conf == 1.0

    # Fuzzy path: unknown mapping but artifact appears and group matches partially
    gav2 = GAVCoordinate("com.acme.test", "custom-artifact", "1.2.3")
    cve2 = {
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "criteria": "cpe:2.3:a:acme:custom-artifact:*:*:*:*:*:*:*:*",
                                "versionStartIncluding": "1.0",
                                "versionEndExcluding": "2.0",
                            }
                        ]
                    }
                ]
            }
        ]
    }
    conf2 = matcher.match_gav_to_cve(gav2, cve2)
    assert conf2 is not None and 0.5 <= conf2 <= 0.9

    # Negative due to generic artifact name
    gav3 = GAVCoordinate("org.example", "core", "1.0.0")
    conf3 = matcher.match_gav_to_cve(gav3, cve2)
    assert conf3 is None
