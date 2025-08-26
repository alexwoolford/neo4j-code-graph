#!/usr/bin/env python3

from __future__ import annotations

from typing import Any


def extract_dependencies_from_graph(session: Any) -> list[dict[str, Any]]:
    """Return dependencies from the graph as dicts with package, group_id, artifact_id, version."""
    deps_query = (
        "MATCH (ed:ExternalDependency) "
        "RETURN ed.package AS import_path, ed.group_id AS group_id, ed.artifact_id AS artifact_id, ed.version AS version"
    )
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
    return dependencies


def prepare_versioned_dependencies(dependencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter for dependencies that have a concrete version (not 'unknown')."""
    return [
        dep
        for dep in dependencies
        if dep.get("group_id")
        and dep.get("artifact_id")
        and dep.get("version")
        and dep.get("version") != "unknown"
    ]


def compute_precise_matches(
    versioned_deps: list[dict[str, Any]], cve_data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compute precise GAV-based matches using the project's matcher when available."""
    try:
        from src.security.gav_cve_matcher import GAVCoordinate, PreciseGAVMatcher

        matcher = PreciseGAVMatcher()
        precise: list[dict[str, Any]] = []
        gav_deps: list[tuple[Any, str]] = []
        for dep in versioned_deps:
            gav = GAVCoordinate(dep["group_id"], dep["artifact_id"], dep["version"])  # type: ignore[index]
            gav_deps.append((gav, str(dep.get("package") or "")))
        for gav, package in gav_deps:
            for cve in cve_data:
                confidence = matcher.match_gav_to_cve(gav, cve)
                if confidence is not None:
                    precise.append(
                        {
                            "cve_id": cve.get("id", ""),
                            "dep_package": package,
                            "confidence": confidence,
                            "match_type": "precise_gav",
                        }
                    )
        return precise
    except Exception:
        return []


def compute_text_versioned_matches(
    versioned_deps: list[dict[str, Any]], cve_data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Heuristic text-based matches requiring versioned dependencies (low confidence)."""
    matches: list[dict[str, Any]] = []
    for dep in versioned_deps:
        package = str(dep.get("package") or "")
        if not package:
            continue
        last_seg = package.split(".")[-1].lower() if "." in package else package.lower()
        for cve in cve_data:
            desc = str(cve.get("description", "")).lower()
            if package.lower() in desc or last_seg in desc:
                matches.append(
                    {
                        "cve_id": cve.get("id", ""),
                        "dep_package": package,
                        "confidence": 0.5,
                        "match_type": "text_versioned",
                    }
                )
    return matches


__all__ = [
    "extract_dependencies_from_graph",
    "prepare_versioned_dependencies",
    "compute_precise_matches",
    "compute_text_versioned_matches",
]
