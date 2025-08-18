#!/usr/bin/env python3
import pytest


@pytest.mark.security
def test_affects_only_links_to_versioned_dependencies(neo4j_driver):
    from src.security.cve_analysis import CVEAnalyzer

    analyzer = CVEAnalyzer(driver=neo4j_driver, database=None)

    with neo4j_driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        # Unversioned dep
        s.run("MERGE (ed:ExternalDependency {package:'com.example.Example'})").consume()
        # Versioned dep
        s.run(
            """
            MERGE (ed:ExternalDependency {package:'org.reflections.Reflections'})
            SET ed.language='java', ed.ecosystem='maven', ed.version='0.10.2'
            """
        ).consume()

        # Seed CVEs (IDs are created in _link_cves_to_dependencies via create_vulnerability_graph,
        # but for this test we only need the linking step and the presence of CVE nodes)
        s.run("MERGE (:CVE {id:'CVE-TEXT-1'})").consume()
        s.run("MERGE (:CVE {id:'CVE-TEXT-2'})").consume()

        # Minimal cve_data dicts; descriptions mention both deps
        cve_data = [
            {"id": "CVE-TEXT-1", "description": "Issue in org.reflections Reflections library"},
            {"id": "CVE-TEXT-2", "description": "Problem affects com.example Example module"},
        ]

        # Run linking
        analyzer._link_cves_to_dependencies(s, cve_data)  # type: ignore[attr-defined]

        # Assert links only to versioned dep
        rows = s.run(
            "MATCH (c:CVE)-[:AFFECTS]->(ed:ExternalDependency) RETURN c.id AS id, ed.package AS pkg"
        ).data()
        pkgs = {r["pkg"] for r in rows}
        assert "org.reflections.Reflections" in pkgs
        assert "com.example.Example" not in pkgs
