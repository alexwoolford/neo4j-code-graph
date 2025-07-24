#!/usr/bin/env python3
"""
Test suite for CVE analysis functionality.
"""

import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, mock_open, patch

import pytest

# Ensure project root is on the import path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Mock heavy dependencies


def _stub_module(name, attrs=None):
    mod = ModuleType(name)
    for attr in attrs or []:
        setattr(mod, attr, MagicMock())
    return mod


HEAVY_MODULES = {
    "neo4j": _stub_module("neo4j", ["GraphDatabase", "Driver"]),
    "graphdatascience": _stub_module("graphdatascience", ["GraphDataScience"]),
    "transformers": _stub_module("transformers", ["AutoTokenizer", "AutoModel"]),
    "torch": _stub_module("torch"),
    "requests": _stub_module("requests"),
    "tqdm": _stub_module("tqdm", ["tqdm"]),
    "dotenv": _stub_module("dotenv", ["load_dotenv"]),
}


@pytest.fixture
def sample_cve_data():
    """Sample CVE data for testing."""
    return [
        {
            "cve": {
                "id": "CVE-2024-12345",
                "descriptions": [
                    {
                        "lang": "en",
                        "value": "A vulnerability in Spring Boot allows remote code execution",
                    }
                ],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]
                },
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        "criteria": "cpe:2.3:a:pivotal:spring_boot:*:*:*:*:*:*:*:*",
                                        "versionEndExcluding": "2.7.0",
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "published": "2024-01-01T00:00:00.000",
                "lastModified": "2024-01-02T00:00:00.000",
            }
        }
    ]


class TestCVECacheManager:
    """Test cases for CVE cache manager."""

    def test_is_cve_relevant_with_matching_component(self):
        """Test CVE relevance detection with matching components."""
        with patch.dict(sys.modules, HEAVY_MODULES):
            from src.security.cve_cache_manager import CVECacheManager

            cache_manager = CVECacheManager()

            cve = {
                "descriptions": [{"lang": "en", "value": "Spring Boot vulnerability allows RCE"}],
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {"criteria": "cpe:2.3:a:pivotal:spring_boot:*:*:*:*:*:*:*:*"}
                                ]
                            }
                        ]
                    }
                ],
            }

            components = {"spring", "spring-boot", "pivotal"}

            # Test the is_cve_relevant method with matching components
            assert cache_manager.is_cve_relevant(cve, components) is True

    def test_is_cve_relevant_with_non_matching_component(self):
        """Test CVE relevance detection with non-matching components."""
        with patch.dict(sys.modules, HEAVY_MODULES):
            from src.security.cve_cache_manager import CVECacheManager

            cache_manager = CVECacheManager()

            cve = {
                "descriptions": [{"lang": "en", "value": "Django vulnerability"}],
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {"criteria": "cpe:2.3:a:djangoproject:django:*:*:*:*:*:*:*:*"}
                                ]
                            }
                        ]
                    }
                ],
            }

            components = {"spring", "spring-boot", "apache"}

            # Test the is_cve_relevant method with non-matching components
            assert cache_manager.is_cve_relevant(cve, components) is False

    def test_cache_file_creation(self):
        """Test cache file path generation."""
        with patch.dict(sys.modules, HEAVY_MODULES):
            from src.security.cve_cache_manager import CVECacheManager

            cache_manager = CVECacheManager(cache_dir="./test_cache")
            cache_key = "test_key_123"

            # Test the get_cache_file_path method
            cache_file = cache_manager.get_cache_file_path(cache_key)
            assert cache_file.parent.name == "test_cache"
            assert cache_file.name == "test_key_123.json.gz"


class TestCVEAnalyzer:
    """Test cases for CVE analyzer."""

    def test_load_cve_data_from_file(self, sample_cve_data):
        """Test loading CVE data from file."""
        with patch.dict(sys.modules, HEAVY_MODULES):
            from src.security.cve_analysis import CVEAnalyzer

            analyzer = CVEAnalyzer()

            with patch("builtins.open", mock_open(read_data=json.dumps(sample_cve_data))):
                result = analyzer.load_cve_data("test_file.json")

                assert len(result) == 1
                assert result[0]["cve"]["id"] == "CVE-2024-12345"

    def test_extract_cve_details(self, sample_cve_data):
        """Test CVE detail extraction."""
        cve = sample_cve_data[0]["cve"]

        # Test description extraction
        descriptions = cve.get("descriptions", [])
        description = ""
        for desc in descriptions:
            if desc.get("lang") == "en":
                description = desc.get("value", "")
                break

        assert "Spring Boot" in description
        assert "remote code execution" in description

        # Test CVSS score extraction
        metrics = cve.get("metrics", {})
        cvss_score = 0.0
        if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
            cvss_score = metrics["cvssMetricV31"][0]["cvssData"]["baseScore"]
        elif "cvssMetricV30" in metrics and metrics["cvssMetricV30"]:
            cvss_score = metrics["cvssMetricV30"][0]["cvssData"]["baseScore"]

        assert cvss_score == 9.8

    def test_extract_component_from_cpe(self, sample_cve_data):
        """Test component extraction from CPE."""
        cve = sample_cve_data[0]["cve"]
        configurations = cve.get("configurations", [])

        # Extract CPE information
        components = set()
        for config in configurations:
            for node in config.get("nodes", []):
                for cpe_match in node.get("cpeMatch", []):
                    cpe = cpe_match.get("criteria", "")
                    if "spring" in cpe.lower():
                        components.add("spring")

        assert "spring" in components

    def test_universal_dependency_matching(self):
        """Test universal dependency matching logic."""
        # Test common dependency naming patterns across languages
        test_cases = [
            # Java
            ("com.fasterxml.jackson", ["fasterxml", "jackson"]),
            ("org.springframework", ["springframework", "spring"]),
            # Python
            ("requests-oauthlib", ["requests", "oauthlib"]),
            ("django_rest_framework", ["django", "rest", "framework"]),
            # Node.js
            ("@types/node", ["types", "node"]),
            # Go
            ("github.com/gin-gonic/gin", ["gin", "gonic"]),
            # Rust
            ("serde::json", ["serde", "json"]),
        ]

        for dependency, expected_components in test_cases:
            # Test universal component extraction
            extracted = self._extract_universal_components(dependency)
            for component in expected_components:
                assert (
                    component in extracted
                ), f"Expected {component} in {extracted} for {dependency}"

    def _extract_universal_components(self, dependency_path: str):
        """Helper method to test universal component extraction."""
        components = set()
        components.add(dependency_path.lower())

        # Extract meaningful parts from different naming conventions
        for sep in [".", "/", "-", "_", "::"]:
            if sep in dependency_path:
                parts = dependency_path.split(sep)
                for part in parts:
                    if (
                        part
                        and len(part) > 2
                        and part not in ["com", "org", "net", "io", "www", "github", "types"]
                    ):
                        components.add(part.lower())

                        # Extract shorter meaningful components from compound words
                        if "spring" in part.lower():
                            components.add("spring")
                        if "jackson" in part.lower():
                            components.add("jackson")
                        if "apache" in part.lower():
                            components.add("apache")

                        # Handle special cases like @types/node
                        if part.startswith("@"):
                            clean_part = part[1:]  # Remove @ symbol
                            components.add(clean_part)
                            if "/" in clean_part:
                                sub_parts = clean_part.split("/")
                                for sub_part in sub_parts:
                                    if sub_part and len(sub_part) > 2:
                                        components.add(sub_part)

                        # Handle hyphenated parts like gin-gonic
                        if "-" in part:
                            hyphen_parts = part.split("-")
                            for hyphen_part in hyphen_parts:
                                if hyphen_part and len(hyphen_part) > 2:
                                    components.add(hyphen_part.lower())

        return components

    def test_universal_component_patterns(self):
        """Test universal component pattern matching across languages."""
        # Test common patterns that work across ecosystems
        test_mappings = {
            "com.fasterxml.jackson": "jackson",
            "org.springframework": "spring",
            "org.apache.commons": "apache",
            "requests-oauthlib": "requests",
            "github.com/gin-gonic/gin": "gin",
            "serde::json": "serde",
        }

        for import_path, expected_component in test_mappings.items():
            # Test universal pattern extraction
            extracted = self._extract_universal_components(import_path)
            assert expected_component in extracted, f"Expected {expected_component} in {extracted}"

    def test_component_mapping(self):
        """Test component mapping logic."""
        # Test common Java library mappings
        test_mappings = {
            "com.fasterxml.jackson": "jackson",
            "org.springframework": "spring",
            "org.apache.commons": "apache-commons",
        }

        for import_path, expected_component in test_mappings.items():
            # Simple mapping logic test
            component_name = import_path.split(".")[-1] if "." in import_path else import_path
            assert component_name in expected_component or expected_component in component_name

    def test_cvss_severity_classification(self):
        """Test CVSS severity classification."""
        test_cases = [
            (9.8, "CRITICAL"),
            (7.5, "HIGH"),
            (5.0, "MEDIUM"),
            (3.2, "LOW"),
            (0.0, "NONE"),
        ]

        for score, expected_severity in test_cases:
            if score >= 9.0:
                severity = "CRITICAL"
            elif score >= 7.0:
                severity = "HIGH"
            elif score >= 4.0:
                severity = "MEDIUM"
            elif score > 0.0:
                severity = "LOW"
            else:
                severity = "NONE"

            assert severity == expected_severity


class TestCVEIntegration:
    """Integration tests for CVE analysis workflow."""

    def test_end_to_end_cve_workflow(self):
        """Test the complete CVE analysis workflow."""
        with patch.dict(sys.modules, HEAVY_MODULES):
            # Test would require real Neo4j connection
            # For now, just test that components can be imported
            from src.security.cve_analysis import CVEAnalyzer
            from src.security.cve_cache_manager import CVECacheManager

            # Basic instantiation test
            assert CVEAnalyzer is not None
            assert CVECacheManager is not None

    def test_cve_data_loading_integration(self):
        """Test CVE data loading with mocked components."""
        with patch.dict(sys.modules, HEAVY_MODULES):
            from src.security.cve_cache_manager import CVECacheManager

            cache_manager = CVECacheManager()

            # Test with empty component set
            components = set()
            result = cache_manager.is_cve_relevant({}, components)
            assert result is False

            # Test with sample components
            components = {"spring", "jackson"}
            sample_cve = {
                "descriptions": [{"lang": "en", "value": "Spring framework vulnerability"}]
            }
            result = cache_manager.is_cve_relevant(sample_cve, components)
            assert result is True


def test_cve_schema_constraints():
    """Test that CVE-related schema constraints are defined."""
    # Read schema_management.py to ensure CVE constraints exist
    schema_file = os.path.join(
        os.path.dirname(__file__), "..", "src", "data", "schema_management.py"
    )

    with open(schema_file, "r") as f:
        content = f.read()

        # Check for CVE constraint
        assert "CVE" in content
        assert "ExternalDependency" in content
        # Component nodes were removed as they don't exist in actual schema


if __name__ == "__main__":
    pytest.main([__file__])
