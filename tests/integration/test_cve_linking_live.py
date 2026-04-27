"""Live regression: CVE-to-ExternalDependency linking obeys versioned-only AFFECTS rules.

AGENTS.md (cve_handling) requires:
  1. Link CVEs only when version constraints match the dependency version.
  2. Only consider ExternalDependency nodes with version IS NOT NULL for AFFECTS.
  3. Ignore CVEs without version constraints (precise and fuzzy).
  4. Never link to dependencies lacking a version.

This test seeds two ExternalDependency nodes (one versioned jackson-core, one
unversioned) plus one synthetic CVE with a CPE-matched version range, drives
``link_cves_to_dependencies``, and asserts AFFECTS lands on the versioned dep
only -- exercising rules 1, 2, and 4 in a single scenario.
"""

from __future__ import annotations

from typing import Any

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


def _seed_dependencies(session: Any) -> None:
    """Two ExternalDependency nodes: one versioned (jackson), one unversioned."""
    session.run("MATCH (n) DETACH DELETE n").consume()
    session.run(
        """
        MERGE (versioned:ExternalDependency {package: 'com.fasterxml.jackson.core'})
        SET versioned.group_id    = 'com.fasterxml.jackson.core',
            versioned.artifact_id = 'jackson-core',
            versioned.version     = '2.15.0',
            versioned.language    = 'java',
            versioned.ecosystem   = 'maven'
        MERGE (unversioned:ExternalDependency {package: 'org.example.unknown'})
        SET unversioned.group_id    = 'org.example',
            unversioned.artifact_id = 'unknown',
            unversioned.version     = 'unknown',
            unversioned.language    = 'java',
            unversioned.ecosystem   = 'maven'
        """
    ).consume()


def _synthetic_cve_affecting_jackson_2_14_to_2_16() -> dict[str, Any]:
    """A CleanCVE-shaped dict with a CPE configuration matching jackson-core.

    The CPE URI uses the fasterxml:jackson-core vendor:product the matcher
    expects (see PreciseGAVMatcher._load_known_cpe_patterns), and the version
    range covers our seeded 2.15.0 dependency.
    """
    return {
        "id": "CVE-TEST-0001",
        "description": "Synthetic CVE for jackson-core 2.14.x-2.16.x range",
        "cvss_score": 7.5,
        "severity": "HIGH",
        "published": "2025-01-01T00:00:00.000",
        "modified": "2025-01-01T00:00:00.000",
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "criteria": "cpe:2.3:a:fasterxml:jackson-core:*:*:*:*:*:*:*:*",
                                "versionStartIncluding": "2.14.0",
                                "versionEndExcluding": "2.16.0",
                            }
                        ]
                    }
                ]
            }
        ],
    }


def test_affects_only_links_versioned_external_dependencies() -> None:
    from src.data.schema_management import setup_complete_schema
    from src.security.graph_writer import link_cves_to_dependencies

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            setup_complete_schema(session)
            _seed_dependencies(session)

            cve_data = [_synthetic_cve_affecting_jackson_2_14_to_2_16()]
            linked = link_cves_to_dependencies(session, cve_data)
            assert linked == 1, f"expected exactly 1 AFFECTS edge, got {linked}"

            # Versioned jackson-core must have AFFECTS
            rec = session.run(
                """
                MATCH (cve:CVE {id: 'CVE-TEST-0001'})-[r:AFFECTS]->(ed:ExternalDependency)
                WHERE ed.group_id = 'com.fasterxml.jackson.core'
                  AND ed.artifact_id = 'jackson-core'
                  AND ed.version = '2.15.0'
                RETURN count(*) AS c
                """
            ).single()
            assert rec and int(rec["c"]) == 1, "versioned jackson-core should be linked"

            # Unversioned dep must NOT have AFFECTS
            rec = session.run(
                """
                MATCH (cve:CVE {id: 'CVE-TEST-0001'})-[r:AFFECTS]->(ed:ExternalDependency)
                WHERE ed.version IS NULL OR ed.version = 'unknown'
                RETURN count(*) AS c
                """
            ).single()
            assert rec and int(rec["c"]) == 0, "unversioned deps must never get AFFECTS edges"


def test_no_affects_when_cve_has_no_version_constraints() -> None:
    """Rule 3: CVEs without version constraints must not produce AFFECTS edges
    even on a perfectly-versioned matching dependency.
    """
    from src.data.schema_management import setup_complete_schema
    from src.security.graph_writer import link_cves_to_dependencies

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            setup_complete_schema(session)
            _seed_dependencies(session)

            cve_no_range: dict[str, Any] = {
                "id": "CVE-TEST-0002",
                "description": "Synthetic CVE for jackson-core with no version constraints",
                "cvss_score": 5.0,
                "severity": "MEDIUM",
                "published": "2025-01-01T00:00:00.000",
                "modified": "2025-01-01T00:00:00.000",
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        "criteria": "cpe:2.3:a:fasterxml:jackson-core:*:*:*:*:*:*:*:*",
                                        # Intentionally no versionStart*/versionEnd* fields
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
            # link_cves_to_dependencies' annotated type is list[CleanCVE] (the
            # cleaned shape), but at runtime it reads the broader NVD dict
            # (including 'configurations') -- our synthetic CVE is dict-shape
            # compatible.
            linked = link_cves_to_dependencies(session, [cve_no_range])  # type: ignore[list-item]
            assert linked == 0, "CVE without version constraints must not link to anything"

            rec = session.run(
                "MATCH (:CVE {id: 'CVE-TEST-0002'})-[:AFFECTS]->() RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 0
