#!/usr/bin/env python3

"""
EXPLAIN-based smoke tests for Cypher queries.

Skips automatically if Neo4j is not reachable from environment variables.
No writes are performed; only EXPLAIN is used.
"""

import pytest


def _get_driver_or_skip():
    try:
        from neo4j import GraphDatabase

        from src.utils.neo4j_utils import get_neo4j_config
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Neo4j client unavailable: {e}")

    uri, username, password, database = get_neo4j_config()
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        # fast connectivity check
        with driver.session(database=database) as s:
            s.run("RETURN 1").consume()
        return driver, database
    except Exception as e:
        pytest.skip(f"Neo4j not reachable for EXPLAIN tests: {e}")


@pytest.mark.integration
def test_explain_code_analysis_queries():
    driver, database = _get_driver_or_skip()
    with driver.session(database=database) as s:
        # Representative UNWIND/MERGE for File nodes
        q = (
            "EXPLAIN UNWIND $files AS file "
            "MERGE (f:File {path: file.path}) "
            "SET f.language = file.language"
        )
        s.run(q, files=[{"path": "src/Main.java", "language": "java"}]).consume()

        # Representative relationship creation
        q2 = (
            "EXPLAIN UNWIND $rels AS rel "
            "MATCH (f:File {path: rel.file}) MATCH (i:Import {import_path: rel.import}) "
            "MERGE (f)-[:IMPORTS]->(i)"
        )
        s.run(q2, rels=[{"file": "src/Main.java", "import": "org.example.Util"}]).consume()


@pytest.mark.integration
def test_explain_cve_analysis_queries():
    driver, database = _get_driver_or_skip()
    with driver.session(database=database) as s:
        q = "EXPLAIN MATCH (cve:CVE) WHERE cve.cvss_score >= $t " "RETURN cve LIMIT 1"
        s.run(q, t=7.0).consume()


@pytest.mark.integration
def test_explain_cleanup_show_indexes():
    driver, database = _get_driver_or_skip()
    with driver.session(database=database) as s:
        s.run("EXPLAIN SHOW INDEXES").consume()
        s.run("EXPLAIN SHOW CONSTRAINTS").consume()
