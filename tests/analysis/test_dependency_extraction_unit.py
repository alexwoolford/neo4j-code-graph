from pathlib import Path


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
