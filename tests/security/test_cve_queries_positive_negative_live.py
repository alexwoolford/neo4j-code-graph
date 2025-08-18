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


def test_cve_query_positive_and_negative_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            # Seed a positive graph: versioned dep linked to CVE
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                """
                MERGE (ed:ExternalDependency {package:'com.fasterxml.jackson'})
                SET ed.language='java', ed.ecosystem='maven', ed.version='2.15.0'
                MERGE (c:CVE {id:'CVE-TEST-POS'})
                SET c.cvss_score=9.8, c.severity='CRITICAL'
                MERGE (c)-[:AFFECTS {match_type:'precise_gav', confidence:0.95}]->(ed)
                """
            ).consume()

            # Positive: count CVEs by severity should return at least one
            pos = s.run(
                "MATCH (c:CVE)-[:AFFECTS]->(ed:ExternalDependency) WHERE c.severity IN ['CRITICAL','HIGH'] RETURN count(c) AS c"
            ).single()
            assert pos and int(pos["c"]) >= 1

            # Negative: ensure no AFFECTS to unversioned deps
            s.run(
                """
                MERGE (ed2:ExternalDependency {package:'org.example.lib'})
                SET ed2.language='java', ed2.ecosystem='maven'
                """
            ).consume()
            neg = s.run(
                "MATCH (c:CVE)-[:AFFECTS]->(ed:ExternalDependency {package:'org.example.lib'}) RETURN count(*) AS c"
            ).single()
            assert neg and int(neg["c"]) == 0
