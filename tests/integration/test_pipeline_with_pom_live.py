#!/usr/bin/env python3

from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def _get_driver_or_skip():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")
    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_pipeline_live_with_maven_pom(tmp_path: Path):
    from src.analysis.code_analysis import (
        bulk_create_nodes_and_relationships,
        extract_file_data,
    )
    from src.data.schema_management import setup_complete_schema

    # Build a tiny repo with a pom.xml declaring a versioned dep
    repo = tmp_path / "tiny"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    _write(
        repo / "src" / "A.java",
        """
        package p;
        import com.fasterxml.jackson.core.JsonFactory; // external import
        class A { void a() { JsonFactory f = null; } }
        """,
    )
    _write(
        repo / "pom.xml",
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>p</groupId><artifactId>a</artifactId><version>1.0.0</version>
          <dependencies>
            <dependency>
              <groupId>com.fasterxml.jackson.core</groupId>
              <artifactId>jackson-core</artifactId>
              <version>2.15.0</version>
            </dependency>
          </dependencies>
        </project>
        """,
    )

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)

            # Extract and load
            files_data = []
            for f in (repo / "src").rglob("*.java"):
                fd = extract_file_data(f, repo)
                if fd:
                    files_data.append(fd)

            # Gather dependency versions from pom.xml (as the DAG would)
            from src.analysis.dependency_extraction import (
                extract_enhanced_dependencies_for_neo4j,
            )

            dep_versions = extract_enhanced_dependencies_for_neo4j(repo)

            # No embeddings provided (current DAG defaults) but we pass empty arrays for API shape
            bulk_create_nodes_and_relationships(
                session,
                files_data,
                file_embeddings=[],
                method_embeddings=[],
                dependency_versions=dep_versions,
            )

            # Now use the loader's import->dependency linking Cypher to create `ExternalDependency`
            session.run(
                """
                MATCH (i:Import)
                WITH i, split(i.import_path, '.') AS parts
                WHERE size(parts) >= 3
                WITH i, parts[0] + '.' + parts[1] + '.' + parts[2] AS base_package
                MERGE (e:ExternalDependency {package: base_package})
                SET e.language = 'java', e.ecosystem = 'maven'
                MERGE (i)-[:DEPENDS_ON]->(e)
                """
            ).consume()

            # Assert presence of import and dependency link
            rec = session.run(
                "MATCH (:Import)-[:DEPENDS_ON]->(:ExternalDependency) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1
