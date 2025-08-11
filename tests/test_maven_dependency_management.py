from __future__ import annotations

import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


add_src_to_path()

from analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j  # noqa: E402

POM_WITH_DM = """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.slf4j</groupId>
        <artifactId>slf4j-api</artifactId>
        <version>2.0.13</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
    </dependency>
  </dependencies>
</project>
""".strip()


def test_maven_dependency_management_version_backfill(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pom.xml").write_text(POM_WITH_DM, encoding="utf-8")

    deps = extract_enhanced_dependencies_for_neo4j(repo)
    assert deps["org.slf4j:slf4j-api:2.0.13"] == "2.0.13"
