from __future__ import annotations

import logging
from typing import Any

from src.security.types import CleanCVE

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
    deps_query = """
        MATCH (ed:ExternalDependency)
        RETURN ed.package AS import_path,
               ed.group_id AS group_id,
               ed.artifact_id AS artifact_id,
               ed.version AS version
        """
    deps_result = session.run(deps_query)
    dependencies: list[dict[str, Any]] = []
    for record in deps_result:
        rec = dict(record)
        dependencies.append(
            {
                "package": rec.get("import_path"),
                "group_id": rec.get("group_id"),
                "artifact_id": rec.get("artifact_id"),
                "version": rec.get("version"),
            }
        )

    if not dependencies:
        logger.warning("No external dependencies found in graph")
        return 0

    try:
        from src.security.gav_cve_matcher import GAVCoordinate, PreciseGAVMatcher

        matcher = PreciseGAVMatcher()
        gav_dependencies: list[tuple[Any, str]] = []
        for dep in dependencies:
            if (
                dep["group_id"]
                and dep["artifact_id"]
                and dep["version"]
                and dep["version"] != "unknown"
            ):
                gav = GAVCoordinate(dep["group_id"], dep["artifact_id"], dep["version"])
                gav_dependencies.append((gav, dep["package"]))

        precise_matches: list[dict[str, Any]] = []
        if gav_dependencies:
            for gav, package in gav_dependencies:
                for cve in cve_data:
                    confidence = matcher.match_gav_to_cve(gav, cve)
                    if confidence is not None:
                        precise_matches.append(
                            {
                                "cve_id": cve.get("id", ""),
                                "dep_package": package,
                                "confidence": confidence,
                                "match_type": "precise_gav",
                            }
                        )
    except ImportError:
        logger.warning("Precise GAV matcher not available, skipping precise matching")
        precise_matches = []

    all_matches: list[dict[str, Any]] = precise_matches

    for dep in dependencies:
        if not (dep.get("version") and dep.get("version") != "unknown"):
            continue
        package = str(dep.get("package") or "")
        if not package:
            continue
        for cve in cve_data:
            desc = str(cve.get("description", "")).lower()
            last_seg = package.split(".")[-1].lower() if "." in package else package.lower()
            if package.lower() in desc or last_seg in desc:
                all_matches.append(
                    {
                        "cve_id": cve.get("id", ""),
                        "dep_package": package,
                        "confidence": 0.5,
                        "match_type": "text_versioned",
                    }
                )

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
