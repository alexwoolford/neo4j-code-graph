#!/usr/bin/env python3
from pathlib import Path

import pytest


@pytest.mark.security
def test_cve_queries_run_cleanly(neo4j_driver):
    # Seed a tiny vulnerable graph with concrete version
    with neo4j_driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        s.run(
            """
            MERGE (ed:ExternalDependency {package:'org.reflections.Reflections'})
            SET ed.language='java', ed.ecosystem='maven', ed.version='0.10.2'
            MERGE (c:CVE {id:'CVE-2099-0001'})
            SET c.cvss_score=9.1, c.severity='CRITICAL'
            MERGE (c)-[:AFFECTS {match_type:'precise_gav', confidence:0.95}]->(ed)
            """
        ).consume()

        # Load cypher templates and execute each query
        cypher_file = Path(__file__).resolve().parents[2] / "cve_queries.cypher"
        assert cypher_file.exists(), "cve_queries.cypher not found"
        text = cypher_file.read_text(encoding="utf-8")

        # naive split on semicolons; keep non-empty statements
        statements = [
            q.strip() for q in text.split(";") if q.strip() and not q.strip().startswith("//")
        ]
        assert statements, "No queries found in cve_queries.cypher"

        ran = 0
        had_rows = False
        for q in statements:
            try:
                result = s.run(q)
                # Consume safely; some queries may be write/DDL
                data = []
                try:
                    data = result.data()
                except Exception:
                    pass
                if data:
                    had_rows = True
                ran += 1
            except Exception as e:  # pragma: no cover - we want the exact failing statement
                raise AssertionError(f"Query failed to execute: {q}\nError: {e}") from e

        assert ran >= 1
        # At least one query should return rows on our seeded graph
        assert had_rows is True
