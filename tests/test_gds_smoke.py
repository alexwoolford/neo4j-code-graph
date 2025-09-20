#!/usr/bin/env python3

"""
GDS smoke tests (integration): minimal in-memory projections that don't write to store.
Skips automatically if GDS is not available.
"""

import pytest


def _get_session_or_skip():
    try:
        from neo4j import GraphDatabase

        from src.utils.neo4j_utils import get_neo4j_config
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Neo4j client unavailable: {e}")

    uri, username, password, database = get_neo4j_config()
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        session = driver.session(database=database)
        # Fast connectivity check
        session.run("RETURN 1").consume()
        return driver, session
    except Exception as e:
        pytest.skip(f"Neo4j not reachable for GDS tests: {e}")


def _require_gds(session):
    try:
        session.run("CALL gds.version()").consume()
    except Exception as e:
        pytest.skip(f"GDS not available: {e}")


@pytest.mark.integration
def test_gds_empty_projection_similarity():
    driver, session = _get_session_or_skip()
    try:
        _require_gds(session)
        # Empty in-memory graph projection for similarity-like topology
        # Use a projection that always yields at least one node to satisfy GDS
        session.run(
            "CALL gds.graph.project.cypher(\n"
            "  $name,\n"
            "  'OPTIONAL MATCH (m:Method) WITH coalesce(id(m), 0) AS id RETURN id LIMIT 1',\n"
            "  'RETURN null AS source, null AS target LIMIT 0'\n"
            ")",
            name="similarityTest",
        ).consume()
        # Drop graph (no-op if not created)
        session.run(
            "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
            name="similarityTest",
        ).consume()
    finally:
        session.close()
        driver.close()


@pytest.mark.integration
def test_gds_empty_projection_centrality():
    driver, session = _get_session_or_skip()
    try:
        _require_gds(session)
        # Empty in-memory graph projection for centrality-like topology
        session.run(
            "CALL gds.graph.project.cypher(\n"
            "  $name,\n"
            "  'OPTIONAL MATCH (m:Method) WITH coalesce(id(m), 0) AS id RETURN id LIMIT 1',\n"
            "  'RETURN null AS source, null AS target LIMIT 0'\n"
            ")",
            name="centralityTest",
        ).consume()
        session.run(
            "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
            name="centralityTest",
        ).consume()
    finally:
        session.close()
        driver.close()
