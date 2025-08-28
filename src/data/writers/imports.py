#!/usr/bin/env python3

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

try:
    _progress = import_module("src.utils.progress")
except Exception:  # pragma: no cover
    _progress = import_module("utils.progress")
progress_range = _progress.progress_range

logger = logging.getLogger(__name__)


def create_imports(
    session: Any,
    files_data: list[dict[str, Any]],
    dependency_versions: dict[str, str] | None = None,
) -> None:
    all_imports = []
    external_dependencies = set()

    for file_data in files_data:
        for import_info in file_data.get("imports", []):
            all_imports.append(import_info)

            if import_info["import_type"] == "external":
                import_path = import_info["import_path"]
                if "." in import_path:
                    parts = import_path.split(".")
                    # Choose the most specific base package (3..5 segments),
                    # preferring keys that appear in dependency_versions.
                    candidate = None
                    if len(parts) >= 3:
                        for k in range(min(len(parts), 5), 2, -1):
                            base = ".".join(parts[:k])
                            if dependency_versions and (
                                base in dependency_versions
                                or any(
                                    (dv_key.startswith(base) or base.startswith(dv_key))
                                    for dv_key in dependency_versions.keys()
                                    if ":" not in dv_key
                                )
                            ):
                                candidate = base
                                break
                        if candidate is None:
                            candidate = (
                                ".".join(parts[: min(4, len(parts))])
                                if len(parts) >= 4
                                else ".".join(parts[:3])
                            )
                        external_dependencies.add(candidate)

    if all_imports:
        logger.info(f"Creating {len(all_imports)} import nodes...")
        batch_size = 1000
        total_batches = (len(all_imports) + batch_size - 1) // batch_size
        logger.info(f"Creating {len(all_imports)} import nodes in {total_batches} batches...")

        for i in progress_range(
            0, len(all_imports), batch_size, total=total_batches, desc="Import nodes"
        ):
            batch = all_imports[i : i + batch_size]

            session.run(
                """
                UNWIND $imports AS imp
                MERGE (i:Import {import_path: imp.import_path})
                SET i.is_static = imp.is_static,
                    i.is_wildcard = imp.is_wildcard,
                    i.import_type = imp.import_type
                """,
                imports=batch,
            )

        logger.info(
            "Creating %d IMPORTS relationships in %d batches..." % (len(all_imports), total_batches)
        )

        for i in progress_range(
            0, len(all_imports), batch_size, total=total_batches, desc="IMPORTS rels"
        ):
            batch = all_imports[i : i + batch_size]

            session.run(
                "UNWIND $imports AS imp "
                "MATCH (f:File {path: imp.file}) "
                "MATCH (i:Import {import_path: imp.import_path}) "
                "MERGE (f)-[:IMPORTS]->(i)",
                imports=batch,
            )

    if external_dependencies:
        logger.info(f"Creating {len(external_dependencies)} external dependency nodes...")
        dependency_nodes = []

        for dep in external_dependencies:
            version = None
            group_id = None
            artifact_id = None

            if dependency_versions:
                # 1) Exact group match
                if dep in dependency_versions:
                    version = dependency_versions[dep]
                # 2) Longest group prefix match
                if version is None:
                    longest = ""
                    longest_ver = None
                    for dep_key, dep_version in dependency_versions.items():
                        if ":" in dep_key:
                            continue
                        if dep.startswith(dep_key) or dep_key.startswith(dep):
                            if len(dep_key) > len(longest):
                                longest = dep_key
                                longest_ver = dep_version
                    if longest_ver is not None:
                        version = longest_ver

                # 3) Artifact-aware match using GAV keys, including known Jackson mapping
                #    Prefer group:artifact that semantically matches the base package.
                best_len = -1
                best_triplet: tuple[str, str, str] | None = None
                for dep_key, dep_version in dependency_versions.items():
                    if ":" in dep_key and len(dep_key.split(":")) == 3:
                        g, a, v = dep_key.split(":")
                        # Heuristic: base package should start with group; if the last segment
                        # of the base looks like an artifact family (e.g., core/databind),
                        # bias toward that artifact.
                        if dep.startswith(g) or g.startswith(dep):
                            score = len(g)
                            last_seg = dep.split(".")[-1].lower()
                            if last_seg in a.lower():
                                score += 10
                            if score > best_len:
                                best_len = score
                                best_triplet = (g, a, v)
                if best_triplet is not None:
                    group_id, artifact_id, version_candidate = best_triplet
                    version = version_candidate or version
                    # Also allow two-part GAV key mapping (group:artifact -> version)
                    two_part_key = f"{group_id}:{artifact_id}"
                    if (
                        version is None
                        and dependency_versions
                        and two_part_key in dependency_versions
                    ):
                        version = dependency_versions[two_part_key]

                # Explicit mapping for common Jackson packages
                if (
                    group_id is None
                    and artifact_id is None
                    and dep.startswith("com.fasterxml.jackson")
                ):
                    # Group for both core and databind artifacts
                    group_id = "com.fasterxml.jackson.core"
                    # Any package under 'com.fasterxml.jackson.core' → jackson-core
                    if dep.startswith("com.fasterxml.jackson.core"):
                        artifact_id = "jackson-core"
                    # Any package under 'com.fasterxml.jackson.databind' → jackson-databind
                    elif dep.startswith("com.fasterxml.jackson.databind"):
                        artifact_id = "jackson-databind"
                    # Look up version from extracted dependency_versions using GAV
                    if artifact_id is not None:
                        gav_key = f"{group_id}:{artifact_id}"
                        for k, v in dependency_versions.items():
                            if isinstance(k, str) and k.startswith(gav_key + ":"):
                                version = v
                                break
                        if version is None and gav_key in dependency_versions:
                            version = dependency_versions[gav_key]

            dependency_node = {"package": dep, "language": "java", "ecosystem": "maven"}

            if group_id:
                dependency_node["group_id"] = group_id
            if artifact_id:
                dependency_node["artifact_id"] = artifact_id
            if version:
                dependency_node["version"] = version

            dependency_nodes.append(dependency_node)

        session.run(
            """
            UNWIND $dependencies AS dep
            MERGE (e:ExternalDependency {package: dep.package})
            SET e.language = dep.language,
                e.ecosystem = dep.ecosystem,
                e.version = CASE WHEN dep.version IS NOT NULL THEN dep.version ELSE e.version END,
                e.group_id = CASE WHEN dep.group_id IS NOT NULL THEN dep.group_id ELSE e.group_id END,
                e.artifact_id = CASE WHEN dep.artifact_id IS NOT NULL THEN dep.artifact_id ELSE e.artifact_id END
            """,
            dependencies=dependency_nodes,
        )

        session.run(
            "MATCH (i:Import) "
            "WHERE i.import_type = 'external' "
            "WITH i, SPLIT(i.import_path, '.') AS parts "
            "WHERE SIZE(parts) >= 3 "
            "WITH i, parts[0] + '.' + parts[1] + '.' + parts[2] AS base_package "
            "MATCH (e:ExternalDependency {package: base_package}) "
            "MERGE (i)-[:DEPENDS_ON]->(e)"
        )
