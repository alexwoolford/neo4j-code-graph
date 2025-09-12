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
    # Establish a strongly-typed view of dependency versions for mypy
    if dependency_versions is None:
        dep_versions: dict[str, str] = {}
    else:
        dep_versions = dependency_versions
    all_imports: list[dict[str, Any]] = []
    external_dependencies: set[str] = set()

    for file_data in files_data:
        for import_info in file_data.get("imports", []):
            all_imports.append(import_info)

            if import_info["import_type"] == "external":
                import_path = import_info["import_path"]
                if "." in import_path:
                    parts = import_path.split(".")
                    # Choose a sensible base package, trimming trailing class-name segments
                    # (those that start with an uppercase letter) and preferring matches that
                    # exist in dependency_versions (group keys without ':').
                    candidate = None
                    group_keys: set[str] = set(dep_versions.keys()) if dep_versions else set()
                    group_keys = {k for k in group_keys if ":" not in k}
                    if len(parts) >= 2:
                        for idx in range(min(len(parts), 5), 1, -1):
                            base_parts = parts[:idx]
                            # Trim trailing capitalized segments (likely class names)
                            while len(base_parts) >= 2 and base_parts[-1][:1].isupper():
                                base_parts = base_parts[:-1]
                            if len(base_parts) < 2:
                                continue
                            base = ".".join(base_parts)
                            if group_keys and base in group_keys:
                                candidate = base
                                break
                            # Also allow prefix compatibility with known group keys
                            if group_keys and any(
                                (g.startswith(base) or base.startswith(g)) for g in group_keys
                            ):
                                candidate = base
                                break
                    if candidate is None:
                        # Sensible fallback: first 3 segments if available, else first 2
                        candidate = ".".join(parts[:3]) if len(parts) >= 3 else ".".join(parts[:2])
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
        dependency_nodes: list[dict[str, Any]] = []

        for dep in external_dependencies:
            version = None
            group_id = None
            artifact_id = None

            if dep_versions:
                # 1) Exact group match
                if dep in dep_versions:
                    version = dep_versions[dep]
                # 2) Longest group prefix match
                if version is None:
                    longest = ""
                    longest_ver = None
                    for dep_key, dep_version in dep_versions.items():
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
                for dep_key, dep_version in dep_versions.items():
                    if ":" in dep_key and len(dep_key.split(":")) == 3:
                        g, a, ver = str(dep_key).split(":")
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
                                best_triplet = (g, a, ver)
                if best_triplet is not None:
                    group_id, artifact_id, version_candidate = best_triplet
                    version = version_candidate or version
                    # Also allow two-part GAV key mapping (group:artifact -> version)
                    two_part_key = f"{group_id}:{artifact_id}"
                    if version is None and two_part_key in dep_versions:
                        version = dep_versions[two_part_key]

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
                        for k, val in dep_versions.items():
                            if k.startswith(gav_key + ":"):
                                version = val
                                break
                        if version is None and gav_key in dep_versions:
                            version = dep_versions[gav_key]

                # Targeted mappings for known libraries whose import packages differ from Maven groupIds
                if (
                    group_id is None
                    and artifact_id is None
                    and dep.startswith("com.salesforce.emp")
                ):
                    # Map Salesforce EMP connector imports -> com.pontusvision.salesforce:emp-connector
                    group_id = "com.pontusvision.salesforce"
                    artifact_id = "emp-connector"
                    gav_key = f"{group_id}:{artifact_id}"
                    # Prefer full GAV with version
                    for k, val in dep_versions.items():
                        if k.startswith(gav_key + ":"):
                            version = val
                            break
                    if version is None and gav_key in dep_versions:
                        version = dep_versions[gav_key]

                if group_id is None and artifact_id is None and dep.startswith("org.cometd."):
                    # Map CometD client imports -> org.cometd.java:cometd-java-client
                    group_id = "org.cometd.java"
                    artifact_id = "cometd-java-client"
                    gav_key = f"{group_id}:{artifact_id}"
                    for k, val in dep_versions.items():
                        if k.startswith(gav_key + ":"):
                            version = val
                            break
                    if version is None and gav_key in dep_versions:
                        version = dep_versions[gav_key]

                # Additional targeted mappings for common ecosystems
                if group_id is None and artifact_id is None:
                    prefix_to_gav: list[tuple[str, tuple[str, str]]] = [
                        ("org.apache.kafka.clients", ("org.apache.kafka", "kafka-clients")),
                        ("org.apache.kafka.common", ("org.apache.kafka", "kafka-clients")),
                        ("org.slf4j", ("org.slf4j", "slf4j-api")),
                        (
                            "org.springframework.boot.autoconfigure",
                            ("org.springframework.boot", "spring-boot-autoconfigure"),
                        ),
                        ("org.springframework.boot", ("org.springframework.boot", "spring-boot")),
                        ("org.springframework.context", ("org.springframework", "spring-context")),
                        ("org.springframework.beans", ("org.springframework", "spring-beans")),
                        (
                            "org.springframework.stereotype",
                            ("org.springframework", "spring-context"),
                        ),
                        (
                            "org.springframework.kafka",
                            ("org.springframework.kafka", "spring-kafka"),
                        ),
                    ]
                    for prefix, (g, a) in prefix_to_gav:
                        if dep.startswith(prefix):
                            group_id, artifact_id = g, a
                            gav_key = f"{group_id}:{artifact_id}"
                            # Prefer full GAV with version
                            for k, val in dep_versions.items():
                                if k.startswith(gav_key + ":"):
                                    version = val
                                    break
                            if version is None and gav_key in dep_versions:
                                version = dep_versions[gav_key]
                            break

            # If Jackson generic package, emit both core and databind nodes when versions are known
            if dep == "com.fasterxml.jackson":
                jackson_variants = []
                for art in ("jackson-core", "jackson-databind"):
                    g = "com.fasterxml.jackson.core"
                    v: str | None = None
                    gav_key = f"{g}:{art}"
                    # Prefer full GAV with version
                    for k, val in dep_versions.items():
                        if k.startswith(gav_key + ":"):
                            v = val
                            break
                    if v is None and gav_key in dep_versions:
                        v = dep_versions[gav_key]
                    jackson_variants.append(
                        {
                            "package": f"{g}.{art}",
                            "language": "java",
                            "ecosystem": "maven",
                            "group_id": g,
                            "artifact_id": art,
                            **({"version": v} if v else {}),
                        }
                    )
                dependency_nodes.extend(jackson_variants)
            else:
                dependency_node: dict[str, Any] = {
                    "package": dep,
                    "language": "java",
                    "ecosystem": "maven",
                }

                if group_id:
                    dependency_node["group_id"] = group_id
                if artifact_id:
                    dependency_node["artifact_id"] = artifact_id
                if version:
                    dependency_node["version"] = version

                # If we identified GAV, prefer a package key that uniquely identifies the artifact
                if group_id and artifact_id:
                    dependency_node["package"] = f"{group_id}.{artifact_id}"

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
            """
            MATCH (i:Import)
            WHERE i.import_type = 'external'
            WITH i, SPLIT(i.import_path, '.') AS parts
            WITH i,
                 CASE WHEN SIZE(parts) >= 4 THEN parts[0]+'.'+parts[1]+'.'+parts[2]+'.'+parts[3] ELSE NULL END AS p4,
                 CASE WHEN SIZE(parts) >= 3 THEN parts[0]+'.'+parts[1]+'.'+parts[2] ELSE NULL END AS p3,
                 CASE WHEN SIZE(parts) >= 2 THEN parts[0]+'.'+parts[1] ELSE NULL END AS p2
            MATCH (e:ExternalDependency)
            WHERE (e.package IS NOT NULL AND e.package IN [p4, p3, p2])
               OR (e.group_id IS NOT NULL AND e.group_id IN [p4, p3, p2])
            MERGE (i)-[:DEPENDS_ON]->(e)
            """
        )
