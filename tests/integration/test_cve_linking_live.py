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


def test_affects_links_dependency_with_maven_version_range() -> None:
    """B4 / M2: a dep declared as a Maven range like [8.18,10.0) is matched
    against CVE version ranges by parsing the bounds, not by trying to
    feed the bracketed string into packaging.Version.
    """
    from src.data.schema_management import setup_complete_schema
    from src.security.graph_writer import link_cves_to_dependencies

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Disable GHSA augmentation in the live test to keep it deterministic
            # and offline.
            import os as _os

            _os.environ["CODE_GRAPH_DISABLE_GHSA"] = "1"
            setup_complete_schema(session)
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)
            session.run(
                """
                MERGE (ed:ExternalDependency {package: 'com.puppycrawl.tools'})
                SET ed.group_id = 'com.puppycrawl.tools',
                    ed.artifact_id = 'checkstyle',
                    ed.version = '[8.18,10.0)',
                    ed.language = 'java',
                    ed.ecosystem = 'maven'
                """
            ).consume()

            cve = {
                "id": "CVE-TEST-RANGE",
                "description": "Synthetic CVE affecting checkstyle 7.0 to <9.0",
                "cvss_score": 6.5,
                "severity": "MEDIUM",
                "published": "2024-01-01T00:00:00.000",
                "modified": "2024-01-01T00:00:00.000",
                "configurations": [
                    {
                        "nodes": [
                            {
                                "cpeMatch": [
                                    {
                                        "criteria": "cpe:2.3:a:checkstyle:checkstyle:*:*:*:*:*:*:*:*",
                                        "versionStartIncluding": "7.0",
                                        "versionEndExcluding": "9.0",
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
            linked = link_cves_to_dependencies(session, [cve])  # type: ignore[list-item]
            # The dep range [8.18,10.0) overlaps [7.0,9.0): the lower bound 8.18
            # falls in the vulnerable range, so we expect 1 AFFECTS edge.
            assert linked == 1, (
                f"expected 1 AFFECTS edge for [8.18,10.0) vs [7.0,9.0); got {linked}; "
                "indicates Maven range parsing regression (M2)"
            )

            rec = session.run(
                """
                MATCH (:CVE {id: 'CVE-TEST-RANGE'})-[:AFFECTS]->
                      (ed:ExternalDependency {artifact_id: 'checkstyle'})
                RETURN count(*) AS c
                """
            ).single()
            assert rec and int(rec["c"]) == 1


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
