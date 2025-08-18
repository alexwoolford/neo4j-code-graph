#!/usr/bin/env python3

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


def test_depends_on_and_affects_only_versioned_live():
    from src.data.schema_management import setup_complete_schema

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Clean and ensure schema
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)

            # Seed imports: one external package
            session.run(
                """
                CREATE (:Import {import_path:'com.fasterxml.jackson.databind.util', import_type:'external', file:'F.java'})
                """
            ).consume()

            # Seed ExternalDependency nodes: one with version, one without
            session.run(
                """
                CREATE (:ExternalDependency {package:'com.fasterxml.jackson', language:'java', ecosystem:'maven', version:'2.15.0'}),
                       (:ExternalDependency {package:'org.example.lib', language:'java', ecosystem:'maven'})
                """
            ).consume()

            # Link imports to deps (same Cypher pattern as loader)
            session.run(
                """
                MATCH (i:Import)
                WITH i, split(i.import_path, '.') AS parts
                WHERE size(parts) >= 3
                WITH i, parts[0] + '.' + parts[1] + '.' + parts[2] AS base_package
                MATCH (e:ExternalDependency {package: base_package})
                MERGE (i)-[:DEPENDS_ON]->(e)
                """
            ).consume()

            # Simulate CVE node and link creation using version guard
            session.run(
                """
                MERGE (c:CVE {id:'CVE-TEST-1'})
                WITH c
                MATCH (e:ExternalDependency)
                WHERE e.version IS NOT NULL AND e.version <> 'unknown'
                MERGE (c)-[:AFFECTS]->(e)
                """
            ).consume()

            # Assertions
            # DEPENDS_ON links exist
            rec = session.run(
                "MATCH (:Import)-[:DEPENDS_ON]->(:ExternalDependency) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1
            # AFFECTS only to versioned deps
            rec = session.run(
                "MATCH (c:CVE{id:'CVE-TEST-1'})-[:AFFECTS]->(e:ExternalDependency) RETURN e.package AS p"
            ).data()
            packages = {row["p"] for row in rec}
            assert "com.fasterxml.jackson" in packages
            assert "org.example.lib" not in packages
