#!/usr/bin/env python3
import pytest


@pytest.mark.security
def test_affects_only_links_to_versioned_dependencies(neo4j_driver):
    from src.security.cve_analysis import CVEAnalyzer

    analyzer = CVEAnalyzer(driver=neo4j_driver, database=None)

    with neo4j_driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        # Unversioned dep (should never be linked)
        s.run(
            "MERGE (ed:ExternalDependency {package:'com.example.example', language:'java', ecosystem:'maven'})"
        ).consume()
        # Versioned dep with GAV fields for precise matching
        s.run(
            """
            MERGE (ed:ExternalDependency {package:'org.reflections.reflections'})
            SET ed.language='java', ed.ecosystem='maven', ed.group_id='org.reflections', ed.artifact_id='reflections', ed.version='0.10.2'
            """
        ).consume()

        # Seed CVEs (IDs are created in _link_cves_to_dependencies via create_vulnerability_graph,
        # but for this test we only need the linking step and the presence of CVE nodes)
        s.run("MERGE (:CVE {id:'CVE-TEXT-1'})").consume()
        s.run("MERGE (:CVE {id:'CVE-TEXT-2'})").consume()

        # CVE data with precise CPE configurations matching the versioned dependency only
        cve_data = [
            {
                "id": "CVE-TEXT-1",
                "descriptions": [
                    {"lang": "en", "value": "Issue in org.reflections reflections library"}
                ],
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        # Vendor/product align with group_id/artifact_id
                                        "criteria": "cpe:2.3:a:org.reflections:reflections:*:*:*:*:*:*:*:*",
                                        "versionStartIncluding": "0.1.0",
                                        "versionEndExcluding": "0.10.3",
                                    }
                                ]
                            }
                        ]
                    }
                ],
            },
            {
                "id": "CVE-TEXT-2",
                "descriptions": [
                    {"lang": "en", "value": "Problem affects com.example example module"}
                ],
                # No configurations for com.example -> should not match
                "configurations": [],
            },
        ]

        # Run linking
        analyzer._link_cves_to_dependencies(s, cve_data)  # type: ignore[attr-defined]

        # Assert links only to versioned dep
        rows = s.run(
            "MATCH (c:CVE)-[:AFFECTS]->(ed:ExternalDependency) RETURN c.id AS id, ed.package AS pkg"
        ).data()
        pkgs = {r["pkg"] for r in rows}
        assert "org.reflections.reflections" in pkgs
        assert "com.example.example" not in pkgs
