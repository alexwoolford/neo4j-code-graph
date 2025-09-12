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


def test_pipeline_live_with_gradle_build(tmp_path: Path):
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships, extract_file_data
    from src.analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j
    from src.data.schema_management import setup_complete_schema

    # Tiny Gradle repo with a versioned dependency
    repo = tmp_path / "tinyg"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    _write(
        repo / "src" / "A.java",
        """
        package p;
        import org.slf4j.Logger; // external import
        class A { Logger l; }
        """,
    )
    _write(
        repo / "build.gradle",
        """
        plugins { id 'java' }
        repositories { mavenCentral() }
        dependencies {
          implementation 'org.slf4j:slf4j-api:2.0.12'
          testImplementation 'junit:junit:4.13.2'
        }
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

            dep_versions = extract_enhanced_dependencies_for_neo4j(repo)

            bulk_create_nodes_and_relationships(
                session,
                files_data,
                file_embeddings=[],
                method_embeddings=[],
                dependency_versions=dep_versions,
            )

            # Ensure import->dependency link exists
            rec = session.run(
                "MATCH (:Import)-[:DEPENDS_ON]->(:ExternalDependency) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1

            # Versioned dependency node present for slf4j-api 2.0.12
            rec = session.run(
                """
                MATCH (e:ExternalDependency)
                WHERE e.group_id = 'org.slf4j'
                  AND e.artifact_id = 'slf4j-api'
                  AND e.version = '2.0.12'
                RETURN count(e) AS c
                """
            ).single()
            assert rec and int(rec["c"]) == 1
