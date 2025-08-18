#!/usr/bin/env python3
from pathlib import Path


def test_extract_maven_dependencies_simple(tmp_path: Path) -> None:
    from src.analysis.code_analysis import _extract_maven_dependencies  # type: ignore[attr-defined]

    pom = tmp_path / "pom.xml"
    pom.write_text(
        (
            """
            <project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                     xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
              <modelVersion>4.0.0</modelVersion>
              <groupId>com.example</groupId>
              <artifactId>demo</artifactId>
              <version>1.0.0</version>
              <dependencies>
                <dependency>
                  <groupId>org.apache.commons</groupId>
                  <artifactId>commons-lang3</artifactId>
                  <version>3.12.0</version>
                </dependency>
              </dependencies>
            </project>
            """
        ).strip()
    )

    versions = _extract_maven_dependencies(pom)
    assert versions["org.apache.commons.commons-lang3"] == "3.12.0"
    # Full GAV key is also stored
    assert versions["org.apache.commons:commons-lang3:3.12.0"] == "3.12.0"


def test_extract_gradle_dependencies_simple(tmp_path: Path) -> None:
    from src.analysis.code_analysis import (
        _extract_gradle_dependencies,  # type: ignore[attr-defined]
    )

    gradle = tmp_path / "build.gradle"
    gradle.write_text(
        (
            """
            dependencies {
              implementation 'org.apache.commons:commons-lang3:3.11.0'
              testImplementation group: 'junit', name: 'junit', version: '4.13.2'
            }
            """
        ).strip()
    )

    versions = _extract_gradle_dependencies(gradle)
    assert versions["org.apache.commons.commons-lang3"] == "3.11.0"
    assert versions["junit"] == "4.13.2"
    assert versions["org.apache.commons:commons-lang3:3.11.0"] == "3.11.0"
