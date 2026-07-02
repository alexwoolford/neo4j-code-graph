#!/usr/bin/env python3

from __future__ import annotations


def test_is_dependency_affected_improved_boundaries():
    from src.security.cve_analysis import CVEAnalyzer

    a = CVEAnalyzer(driver=None, database="neo4j")
    dep = "com.example.longname.lib"
    # Direct substring match
    assert a._is_dependency_affected_improved(
        dep, "This mentions com.example.longname.lib explicitly"
    )
    # Exactly two parts matched -> True
    assert a._is_dependency_affected_improved(dep, "longname component of example affected") is True
    # Single part matched -> False
    assert a._is_dependency_affected_improved(dep, "only longname present") is False


def test_calculate_match_confidence_improved_boundaries():
    from src.security.cve_analysis import CVEAnalyzer

    a = CVEAnalyzer(driver=None, database="neo4j")
    dep = "org.vendor.productmodule"
    # Direct match -> 0.95
    assert (
        a._calculate_match_confidence_improved(dep, "org.vendor.productmodule vulnerability")
        == 0.95
    )
    # Construct description that matches ~80% of parts
    desc_high = "vendor productmodule impacted"
    conf_high = a._calculate_match_confidence_improved(dep, desc_high)
    assert abs(conf_high - 0.8) < 1e-9 or conf_high >= 0.8
    # ~60% match using a dep that yields three meaningful parts
    dep_mid = "org.vendor.longproduct.module"
    conf_mid = a._calculate_match_confidence_improved(dep_mid, "vendor module affected")
    assert conf_mid == 0.6
    # No match
    assert a._calculate_match_confidence_improved(dep, "unrelated text") == 0.0


def test_universal_search_terms_keeps_distinctive_segments_drops_generic():
    from src.security.cve_analysis import CVEAnalyzer

    a = CVEAnalyzer(driver=None, database="neo4j")
    deps = {
        "java:maven": {
            "org.springframework.core",
            "com.fasterxml.jackson.core",
            "jackson-databind",
            "xstream:1.4.5",  # legacy shape; versions never reach terms today
        }
    }
    terms = a.create_universal_component_search_terms(deps)
    # Full strings included (lowercased)
    assert "org.springframework.core" in terms
    assert "com.fasterxml.jackson.core" in terms
    # Whole artifact names stay whole — hyphens are not split into noise tokens
    assert "jackson-databind" in terms
    assert "databind" not in terms
    # Distinctive vendor segments are kept (they are CPE vendor strings)
    assert "springframework" in terms
    assert "fasterxml" in terms
    # Generic/registrar tokens are excluded as standalone parts
    assert "core" not in terms
    assert "org" not in terms
    assert "com" not in terms
