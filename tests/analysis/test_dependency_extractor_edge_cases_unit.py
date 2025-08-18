#!/usr/bin/env python3

from pathlib import Path


def test_maven_dependency_management_backfill(tmp_path: Path):
    from src.analysis.dependency_extraction import EnhancedDependencyExtractor

    pom = tmp_path / "pom.xml"
    pom.write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>x</groupId><artifactId>y</artifactId><version>1.0.0</version>
          <dependencyManagement>
            <dependencies>
              <dependency>
                <groupId>com.fasterxml.jackson.core</groupId>
                <artifactId>jackson-core</artifactId>
                <version>2.15.0</version>
              </dependency>
            </dependencies>
          </dependencyManagement>
          <dependencies>
            <dependency>
              <groupId>com.fasterxml.jackson.core</groupId>
              <artifactId>jackson-core</artifactId>
            </dependency>
          </dependencies>
        </project>
        """,
        encoding="utf-8",
    )
    deps = EnhancedDependencyExtractor()._extract_maven_dependencies_enhanced(pom)
    gavs = {d.gav.full_coordinate for d in deps}
    assert "com.fasterxml.jackson.core:jackson-core:2.15.0" in gavs


def test_gradle_variable_versions_and_map_style(tmp_path: Path):
    from src.analysis.dependency_extraction import EnhancedDependencyExtractor

    build = tmp_path / "build.gradle"
    build.write_text(
        """
        ext {
          coreVersion = '1.2.3'
          apiVersion = "$coreVersion"
        }
        dependencies {
          implementation 'com.squareup.okhttp3:okhttp:$apiVersion'
          implementation group: 'org.apache.commons', name: 'commons-lang3', version: '3.14.0'
        }
        """,
        encoding="utf-8",
    )
    deps = EnhancedDependencyExtractor()._extract_gradle_dependencies_enhanced(build)
    gavs = {d.gav.full_coordinate for d in deps}
    assert "com.squareup.okhttp3:okhttp:1.2.3" in gavs
    assert "org.apache.commons:commons-lang3:3.14.0" in gavs
