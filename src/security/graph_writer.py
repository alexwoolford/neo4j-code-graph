from __future__ import annotations

import logging
from typing import Any

try:
    from src.security.types import CleanCVE  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from security.types import CleanCVE  # type: ignore

logger = logging.getLogger(__name__)


def create_vulnerability_graph(session: Any, cve_data: list[CleanCVE]) -> int:
    """Deprecated behavior: previously created all CVE nodes up front.

    To avoid disconnected CVEs, this function now no-ops and returns 0.
    CVE nodes are created on-demand during linking only when an AFFECTS edge
    will be written.
    """
    if cve_data:
        logger.info("Skipping upfront CVE node creation; nodes will be created during linking only")
    return 0


def link_cves_to_dependencies(session: Any, cve_data: list[CleanCVE]) -> int:
    logger.info("Linking CVEs to codebase dependencies using precise GAV matching...")
    try:
        from src.security.linking import (  # type: ignore[attr-defined]
            compute_precise_matches,
            extract_dependencies_from_graph,
            prepare_versioned_dependencies,
        )
    except Exception:  # pragma: no cover
        from security.linking import (  # type: ignore
            compute_precise_matches,
            extract_dependencies_from_graph,
            prepare_versioned_dependencies,
        )

    # Provider-agnostic policy: do not use GHSA/Git vendor integrations in linking.

    dependencies = extract_dependencies_from_graph(session)
    logger.info("Dependencies extracted for linking: %d", len(dependencies))
    try:
        logger.debug("Deps sample: %s", dependencies[:5])
    except Exception:
        pass

    if not dependencies:
        logger.warning("No external dependencies found in graph")
        return 0

    versioned_for_precise = prepare_versioned_dependencies(dependencies)
    logger.info(
        "Versioned dependencies eligible for precise matching: %d",
        len(versioned_for_precise),
    )
    try:
        logger.debug("Versioned deps: %s", versioned_for_precise)
    except Exception:
        pass

    # Start with NVD precise matches
    precise_matches = compute_precise_matches(versioned_for_precise, cve_data)

    # No GHSA augmentation; rely solely on NVD precise matches per provider-agnostic policy.
    logger.info("Precise matches computed: %d", len(precise_matches))

    # Strict policy: Only structured matches allowed. Heuristic text matches are disabled
    # to avoid false positives unrelated to the actual dependency coordinates.
    all_matches: list[dict[str, Any]] = precise_matches

    # Enrich links with CVE details so we can MERGE CVE nodes only for linked IDs
    if all_matches:
        by_id = {str(c.get("id", "")): c for c in cve_data}
        for link in all_matches:
            cobj = by_id.get(str(link.get("cve_id", "")), {})
            link["description"] = cobj.get("description", "")
            try:
                link["cvss_score"] = float(cobj.get("cvss_score", 0.0))
            except Exception:
                link["cvss_score"] = 0.0
            link["cvss_vector"] = ""
            link["published"] = cobj.get("published", "")
            link["severity"] = cobj.get("severity", "UNKNOWN")

    if all_matches:
        # Prefer structured match on group_id + artifact_id; fall back to package only if needed
        link_query = """
            UNWIND $links AS link
            MERGE (cve:CVE {id: link.cve_id})
            SET  cve.description = link.description,
                 cve.cvss_score = link.cvss_score,
                 cve.cvss_vector = link.cvss_vector,
                 cve.published = link.published,
                 cve.severity = link.severity,
                 cve.updated_at = datetime()
            WITH cve, link
            OPTIONAL MATCH (ed1:ExternalDependency)
              WHERE ed1.group_id = link.dep_group_id AND ed1.artifact_id = link.dep_artifact_id
                    AND ed1.version IS NOT NULL AND ed1.version <> 'unknown'
            WITH cve, link, ed1
            OPTIONAL MATCH (ed2:ExternalDependency {package: link.dep_package})
              WHERE ed2.version IS NOT NULL AND ed2.version <> 'unknown'
            WITH cve, link, coalesce(ed1, ed2) AS ed
            WHERE ed IS NOT NULL
            MERGE (cve)-[r:AFFECTS]->(ed)
            SET r.confidence = link.confidence,
                r.match_type = link.match_type,
                r.created_at = datetime()
            """
        session.run(link_query, links=all_matches)
        logger.info(f"Created {len(all_matches)} CVE-dependency relationships")
        return len(all_matches)
    return 0
