#!/usr/bin/env python3
"""
Test fixtures for CI environments.

These fixtures provide minimal test data and configurations
that work reliably in CI environments without requiring
large data downloads or external dependencies.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Generator, Optional

import pytest


@pytest.fixture(scope="session")
def ci_test_data_dir() -> Optional[Path]:
    """Get the CI test data directory if it exists."""
    test_data_dir = Path("./test_cache/ci_data")
    if test_data_dir.exists():
        return test_data_dir
    return None


@pytest.fixture(scope="session")
def ci_test_config(ci_test_data_dir) -> Optional[Dict]:
    """Load CI test configuration if available."""
    if ci_test_data_dir is None:
        return None

    config_file = ci_test_data_dir / "ci_test_config.json"
    if config_file.exists():
        with open(config_file, "r") as f:
            return json.load(f)
    return None


@pytest.fixture(scope="session")
def ci_sample_cves(ci_test_data_dir) -> Optional[Dict]:
    """Load sample CVE data for CI testing."""
    if ci_test_data_dir is None:
        return None

    cve_file = ci_test_data_dir / "test_cves.json"
    if cve_file.exists():
        with open(cve_file, "r") as f:
            return json.load(f)
    return None


@pytest.fixture(scope="session")
def ci_sample_java_project(ci_test_config) -> Optional[Path]:
    """Get path to sample Java project for CI testing."""
    if ci_test_config is None:
        return None

    project_path = Path(ci_test_config["sample_project"])
    if project_path.exists():
        return project_path
    return None


@pytest.fixture
def minimal_neo4j_config():
    """Provide Neo4j configuration for CI testing."""
    return {
        "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "username": os.getenv("NEO4J_USERNAME", "neo4j"),
        "password": os.getenv("NEO4J_PASSWORD", "testpassword"),
        "database": os.getenv("NEO4J_DATABASE", "neo4j"),
    }


@pytest.fixture
def temp_java_file() -> Generator[Path, None, None]:
    """Create a temporary Java file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".java", delete=False) as f:
        f.write(
            """
package com.example;

import org.junit.Test;

public class TempTestClass {

    public void simpleMethod() {
        System.out.println("Test method");
    }

    @Test
    public void testMethod() {
        assert true;
    }
}
"""
        )
        temp_path = Path(f.name)

    try:
        yield temp_path
    finally:
        if temp_path.exists():
            temp_path.unlink()


@pytest.fixture
def minimal_dependencies():
    """Provide minimal dependency list for testing."""
    return [
        {
            "groupId": "org.springframework.boot",
            "artifactId": "spring-boot-starter",
            "version": "2.6.0",
        },
        {"groupId": "junit", "artifactId": "junit", "version": "4.12"},
    ]


@pytest.fixture(scope="session")
def skip_if_no_ci_data(ci_test_data_dir):
    """Skip test if CI test data is not available."""
    if ci_test_data_dir is None:
        pytest.skip("CI test data not available - run scripts/prepare_ci_test_data.py first")


@pytest.fixture(scope="session")
def skip_if_no_neo4j(minimal_neo4j_config):
    """Skip test if Neo4j is not available."""
    try:
        from src.utils.common import create_neo4j_driver

        with create_neo4j_driver(
            minimal_neo4j_config["uri"],
            minimal_neo4j_config["username"],
            minimal_neo4j_config["password"],
        ) as driver:
            driver.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j not available: {e}")


def is_ci_environment() -> bool:
    """Check if we're running in a CI environment."""
    ci_indicators = [
        "CI",
        "CONTINUOUS_INTEGRATION",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "JENKINS_URL",
        "TRAVIS",
    ]
    return any(os.getenv(indicator) for indicator in ci_indicators)


@pytest.fixture(scope="session")
def ci_mode():
    """Provide CI mode detection."""
    return is_ci_environment()


@pytest.fixture
def small_test_repo(tmp_path):
    """Create a minimal test repository structure."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Create minimal Java structure
    java_dir = repo_dir / "src" / "main" / "java" / "com" / "test"
    java_dir.mkdir(parents=True)

    # Add a simple Java file
    java_file = java_dir / "SimpleClass.java"
    java_file.write_text(
        """
package com.test;

public class SimpleClass {
    public void hello() {
        System.out.println("Hello World");
    }
}
"""
    )

    # Add pom.xml
    pom_file = repo_dir / "pom.xml"
    pom_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.test</groupId>
    <artifactId>test-project</artifactId>
    <version>1.0.0</version>
</project>
"""
    )

    return repo_dir
