#!/usr/bin/env python3

import pytest


def test_create_universal_component_search_terms_unicode_and_malformed():
    from src.security.cve_analysis import CVEAnalyzer

    analyzer = CVEAnalyzer(driver=None, database="neo4j")
    deps = {
        "maven": {"com.测试:测试-lib:1.0.0", "org.example:café-utils:2.0.0", "group:artifact"},
        "npm": {"lodash@4.17.21", "package@", "@scope/pkg@7.0.0"},
    }
    terms = analyzer.create_universal_component_search_terms(deps)
    assert isinstance(terms, set)
    # Should contain meaningful parts and tolerate unicode
    assert any("lodash" in t for t in terms)
    assert any("café" in t or "utils" in t for t in terms)


@pytest.mark.parametrize(
    "dep,desc,expected",
    [
        ("org.apache.commons.lang3", "... org apache commons lang3 buffer overflow ...", True),
        ("com.vendor.product", "no relevant mention", False),
        # 'core' is filtered as a generic term in the implementation, so this returns False
        ("springframework.core", "affects springframework core classes", False),
    ],
)
def test_is_dependency_affected_improved(dep, desc, expected):
    from src.security.cve_analysis import CVEAnalyzer

    analyzer = CVEAnalyzer(driver=None, database="neo4j")
    assert analyzer._is_dependency_affected_improved(dep, desc) is expected


def test_calculate_match_confidence_thresholds():
    from src.security.cve_analysis import CVEAnalyzer

    analyzer = CVEAnalyzer(driver=None, database="neo4j")
    dep = "com.fasterxml.jackson.core"
    low = analyzer._calculate_match_confidence_improved(dep, "unrelated text")
    mid = analyzer._calculate_match_confidence_improved(dep, "jackson core modules affected")
    high = analyzer._calculate_match_confidence_improved(
        dep, "com fasterxml jackson core vulnerability"
    )
    assert low == 0.0
    assert 0.0 <= mid <= 0.95
    assert high >= mid
