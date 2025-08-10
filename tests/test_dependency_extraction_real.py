import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def test_maven_gav_extraction(tmp_path):
    add_src_to_path()
    from analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    pom = repo_root / "pom.xml"
    pom.write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>com.example</groupId>
          <artifactId>demo</artifactId>
          <version>1.0.0</version>
          <dependencies>
            <dependency>
              <groupId>org.apache.commons</groupId>
              <artifactId>commons-lang3</artifactId>
              <version>3.14.0</version>
            </dependency>
          </dependencies>
        </project>
        """.strip(),
        encoding="utf-8",
    )

    deps = extract_enhanced_dependencies_for_neo4j(repo_root)
    assert deps["org.apache.commons:commons-lang3:3.14.0"] == "3.14.0"
    assert deps["org.apache.commons:commons-lang3"] == "3.14.0"
    assert deps["commons-lang3"] == "3.14.0"


def test_gradle_gav_extraction(tmp_path):
    add_src_to_path()
    from analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    build = repo_root / "build.gradle"
    build.write_text(
        """
        dependencies {
            implementation 'org.slf4j:slf4j-api:2.0.13'
            testImplementation 'junit:junit:4.13.2'
        }
        """.strip(),
        encoding="utf-8",
    )

    deps = extract_enhanced_dependencies_for_neo4j(repo_root)
    assert deps["org.slf4j:slf4j-api:2.0.13"] == "2.0.13"
    assert deps["org.slf4j:slf4j-api"] == "2.0.13"
    assert deps["slf4j-api"] == "2.0.13"
