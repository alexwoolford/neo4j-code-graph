#!/usr/bin/env python3
"""
Prepare minimal test data for CI environments.

This script creates a small, representative dataset that allows
integration tests to run without downloading large amounts of data.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict

# Add src to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from src.security.cve_cache_manager import CVECacheManager
    from src.utils.common import setup_logging
except ImportError:
    # For standalone execution without full dependencies
    def setup_logging(level):
        logging.basicConfig(
            level=getattr(logging, level), format="%(asctime)s [%(levelname)s] %(message)s"
        )

    CVECacheManager = None

logger = logging.getLogger(__name__)


def create_minimal_cve_dataset(cache_dir: Path) -> Dict:
    """Create a minimal CVE dataset for testing."""

    # Sample CVE data that matches the real structure
    sample_cves = [
        {
            "cve": {
                "id": "CVE-2024-TEST-001",
                "descriptions": [
                    {
                        "lang": "en",
                        "value": "A test vulnerability in Spring Boot for CI testing",
                    }
                ],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 7.5, "baseSeverity": "HIGH"}}]
                },
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        "criteria": "cpe:2.3:a:pivotal:spring_boot:2.6.0:*:*:*:*:*:*:*",
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
        },
        {
            "cve": {
                "id": "CVE-2024-TEST-002",
                "descriptions": [
                    {
                        "lang": "en",
                        "value": "A test vulnerability in JUnit for CI testing",
                    }
                ],
                "metrics": {
                    "cvssMetricV31": [{"cvssData": {"baseScore": 5.3, "baseSeverity": "MEDIUM"}}]
                },
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        "criteria": "cpe:2.3:a:junit:junit:4.12:*:*:*:*:*:*:*",
                                        "versionEndExcluding": "4.13",
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "published": "2024-01-01T00:00:00.000",
                "lastModified": "2024-01-02T00:00:00.000",
            }
        },
    ]

    return {"vulnerabilities": sample_cves}


def create_sample_java_project(temp_dir: Path) -> Path:
    """Create a minimal Java project for testing."""

    project_dir = temp_dir / "sample-java-project"
    project_dir.mkdir(parents=True, exist_ok=True)

    # Create a simple Java file
    java_dir = project_dir / "src" / "main" / "java" / "com" / "example"
    java_dir.mkdir(parents=True, exist_ok=True)

    java_file = java_dir / "TestClass.java"
    java_file.write_text(
        """
package com.example;

import org.junit.Test;
import org.springframework.boot.SpringApplication;

public class TestClass {

    public void testMethod() {
        System.out.println("Hello World");
    }

    @Test
    public void simpleTest() {
        assert true;
    }

    public static void main(String[] args) {
        SpringApplication.run(TestClass.class, args);
    }
}
"""
    )

    # Create a pom.xml with dependencies
    pom_file = project_dir / "pom.xml"
    pom_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>

    <groupId>com.example</groupId>
    <artifactId>test-project</artifactId>
    <version>1.0.0</version>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter</artifactId>
            <version>2.6.0</version>
        </dependency>
        <dependency>
            <groupId>junit</groupId>
            <artifactId>junit</artifactId>
            <version>4.12</version>
            <scope>test</scope>
        </dependency>
    </dependencies>
</project>
"""
    )

    logger.info(f"Created sample Java project at {project_dir}")
    return project_dir


def prepare_ci_test_data():
    """Main function to prepare all CI test data."""

    setup_logging("INFO")

    # Create test data directory
    test_data_dir = Path("./test_cache/ci_data")
    test_data_dir.mkdir(parents=True, exist_ok=True)

    logger.info("🏗️  Preparing minimal test data for CI...")

    # 1. Create minimal CVE dataset
    logger.info("📊 Creating minimal CVE dataset...")
    cve_data = create_minimal_cve_dataset(test_data_dir)

    cve_file = test_data_dir / "test_cves.json"
    with open(cve_file, "w") as f:
        json.dump(cve_data, f, indent=2)

    logger.info(f"✅ CVE test data saved to {cve_file}")

    # 2. Create sample Java project
    logger.info("☕ Creating sample Java project...")
    sample_project = create_sample_java_project(test_data_dir)

    # 3. Create test configuration
    config_file = test_data_dir / "ci_test_config.json"
    test_config = {
        "cve_file": str(cve_file),
        "sample_project": str(sample_project),
        "dependencies": ["spring-boot:2.6.0", "junit:4.12"],
        "created_at": "2024-01-01T00:00:00Z",
    }

    with open(config_file, "w") as f:
        json.dump(test_config, f, indent=2)

    logger.info(f"✅ Test configuration saved to {config_file}")

    # 4. Create summary
    logger.info("\n🎯 **CI TEST DATA SUMMARY**")
    logger.info("=" * 50)
    logger.info(f"📂 Data directory: {test_data_dir}")
    logger.info(f"🔒 CVE records: {len(cve_data['vulnerabilities'])}")
    logger.info(f"☕ Java files: {len(list(sample_project.rglob('*.java')))}")
    logger.info(f"📦 Dependencies: {len(test_config['dependencies'])}")
    logger.info("✅ CI test data preparation complete!")

    return str(test_data_dir)


if __name__ == "__main__":
    prepare_ci_test_data()
