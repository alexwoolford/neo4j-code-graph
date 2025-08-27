from __future__ import annotations

import logging
from typing import Any

try:
    from src.security.types import CleanCVE  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from security.types import CleanCVE  # type: ignore

logger = logging.getLogger(__name__)


def create_vulnerability_graph(session: Any, cve_data: list[CleanCVE]) -> int:
    if not cve_data:
        logger.warning("No CVE data to process")
        return 0

    cve_nodes: list[dict[str, Any]] = []
    for cve in cve_data:
        cve_nodes.append(
            {
                "cve_id": cve.get("id", ""),
                "description": cve.get("description", ""),
                "cvss_score": float(cve.get("cvss_score", 0.0)),
                "cvss_vector": "",
                "published": cve.get("published", ""),
                "severity": cve.get("severity", "UNKNOWN"),
            }
        )

    if cve_nodes:
        create_query = """
            UNWIND $cve_nodes AS cve
            MERGE (c:CVE {id: cve.cve_id})
            SET c.description = cve.description,
                c.cvss_score = cve.cvss_score,
                c.cvss_vector = cve.cvss_vector,
                c.published = cve.published,
                c.severity = cve.severity,
                c.updated_at = datetime()
            """
        session.run(create_query, cve_nodes=cve_nodes)
        logger.info(f"Created {len(cve_nodes)} CVE nodes")
    return len(cve_nodes)


def link_cves_to_dependencies(session: Any, cve_data: list[CleanCVE]) -> int:
    logger.info("Linking CVEs to codebase dependencies using precise GAV matching...")
    try:
        from src.security.linking import (  # type: ignore[attr-defined]
            compute_precise_matches,
            compute_text_versioned_matches,
            extract_dependencies_from_graph,
            prepare_versioned_dependencies,
        )
    except Exception:  # pragma: no cover
        from security.linking import (  # type: ignore
            compute_precise_matches,
            compute_text_versioned_matches,
            extract_dependencies_from_graph,
            prepare_versioned_dependencies,
        )

    dependencies = extract_dependencies_from_graph(session)

    if not dependencies:
        logger.warning("No external dependencies found in graph")
        return 0

    versioned_for_precise = prepare_versioned_dependencies(dependencies)
    precise_matches = compute_precise_matches(versioned_for_precise, cve_data)

    all_matches: list[dict[str, Any]] = precise_matches

    version_present = [
        dep for dep in dependencies if dep.get("version") and dep.get("version") != "unknown"
    ]
    all_matches.extend(compute_text_versioned_matches(version_present, cve_data))

    if all_matches:
        link_query = """
            UNWIND $links AS link
            MATCH (cve:CVE {id: link.cve_id})
            MATCH (ed:ExternalDependency {package: link.dep_package})
            WHERE ed.version IS NOT NULL AND ed.version <> 'unknown'
            MERGE (cve)-[r:AFFECTS]->(ed)
            SET r.confidence = link.confidence,
                r.match_type = link.match_type,
                r.created_at = datetime()
            """
        session.run(link_query, links=all_matches)
        logger.info(f"Created {len(all_matches)} CVE-dependency relationships")
        return len(all_matches)
    return 0
