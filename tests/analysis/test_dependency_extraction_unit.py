#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def test_gradle_lockfile_extraction(tmp_path: Path) -> None:
    lock = tmp_path / "gradle.lockfile"
    lock.write_text(
        "\n".join(
            [
                "# Gradle lockfile",
                "org.apache.commons:commons-lang3:3.12.0=locked",
                "com.fasterxml.jackson.core:jackson-core:2.17.1=locked",
            ]
        ),
        encoding="utf-8",
    )

    from src.analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j

    mapping = extract_enhanced_dependencies_for_neo4j(tmp_path)
    assert mapping["org.apache.commons:commons-lang3:3.12.0"] == "3.12.0"
    assert mapping["org.apache.commons:commons-lang3"] == "3.12.0"
    assert mapping["org.apache.commons"] == "3.12.0"
    assert mapping["commons-lang3"] == "3.12.0"


def test_gradle_catalog_extraction(tmp_path: Path) -> None:
    gdir = tmp_path / "gradle"
    gdir.mkdir()
    (gdir / "libs.versions.toml").write_text(
        """
        [versions]
        commons = "3.12.0"
        jackson = "2.17.1"

        [libraries]
        commonsLang = { group = "org.apache.commons", name = "commons-lang3", version.ref = "commons" }
        jacksonCore = { module = "com.fasterxml.jackson.core:jackson-core", version.ref = "jackson" }
        """,
        encoding="utf-8",
    )

    from src.analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j

    mapping = extract_enhanced_dependencies_for_neo4j(tmp_path)
    assert mapping["org.apache.commons:commons-lang3:3.12.0"] == "3.12.0"
    assert mapping["com.fasterxml.jackson.core:jackson-core:2.17.1"] == "2.17.1"


def test_extract_maven_dependencies_with_property_substitution(tmp_path: Path):
    from src.analysis.code_analysis import _extract_maven_dependencies

    pom = tmp_path / "pom.xml"
    pom.write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <properties>
            <jackson.version>2.15.0</jackson.version>
          </properties>
          <dependencies>
            <dependency>
              <groupId>com.fasterxml.jackson.core</groupId>
              <artifactId>jackson-core</artifactId>
              <version>${jackson.version}</version>
            </dependency>
          </dependencies>
        </project>
        """,
        encoding="utf-8",
    )

    deps = _extract_maven_dependencies(pom)
    # Base package or full GAV key expected to map to 2.15.0
    assert (
        deps.get("com.fasterxml.jackson.core") == "2.15.0"
        or deps.get("com.fasterxml.jackson.core:jackson-core:2.15.0") == "2.15.0"
        or deps.get("com.fasterxml.jackson.core.jackson-core") == "2.15.0"
    )


def test_extract_gradle_dependencies_formats(tmp_path: Path):
    from src.analysis.code_analysis import _extract_gradle_dependencies

    g1 = tmp_path / "build.gradle"
    g1.write_text(
        """
        dependencies {
          implementation 'org.slf4j:slf4j-api:2.0.9'
          testImplementation group: 'junit', name: 'junit', version: '4.13.2'
        }
        """,
        encoding="utf-8",
    )

    deps = _extract_gradle_dependencies(g1)
    assert deps["org.slf4j.slf4j-api"] == "2.0.9"
    assert deps["junit.junit"] == "4.13.2"


def test_extract_gradle_version_property_substitution(tmp_path: Path):
    from src.analysis.code_analysis import _extract_gradle_dependencies

    g = tmp_path / "build.gradle"
    g.write_text(
        """
        // simple version property style
        slf4jVersion = '2.0.12'
        dependencies {
          implementation group: 'org.slf4j', name: 'slf4j-api', version: 'slf4jVersion'
        }
        """,
        encoding="utf-8",
    )

    deps = _extract_gradle_dependencies(g)
    assert deps["org.slf4j.slf4j-api"] == "2.0.12"
