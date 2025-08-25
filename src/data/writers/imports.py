#!/usr/bin/env python3

from __future__ import annotations

import logging
from typing import Any

from tqdm import tqdm

from src.analysis.types import FileData

logger = logging.getLogger(__name__)


def create_imports(
    session: Any, files_data: list[FileData], dependency_versions: dict[str, str] | None = None
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
                    if len(parts) >= 3:
                        base_package = ".".join(parts[:3])
                        external_dependencies.add(base_package)

    if all_imports:
        logger.info(f"Creating {len(all_imports)} import nodes...")
        batch_size = 1000
        total_batches = (len(all_imports) + batch_size - 1) // batch_size
        logger.info(f"Creating {len(all_imports)} import nodes in {total_batches} batches...")

        for i in tqdm(
            range(0, len(all_imports), batch_size), total=total_batches, desc="Import nodes"
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

        for i in tqdm(
            range(0, len(all_imports), batch_size), total=total_batches, desc="IMPORTS rels"
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
                if dep in dependency_versions:
                    version = dependency_versions[dep]
                else:
                    for dep_key, dep_version in dependency_versions.items():
                        if dep.startswith(dep_key) or dep_key.startswith(dep):
                            version = dep_version
                            break

                for dep_key, dep_version in dependency_versions.items():
                    if ":" in dep_key and len(dep_key.split(":")) == 3:
                        parts = dep_key.split(":")
                        potential_group = parts[0]
                        potential_artifact = parts[1]

                        if dep.startswith(potential_group) or potential_group in dep:
                            group_id = potential_group
                            artifact_id = potential_artifact
                            version = dep_version
                            break

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
