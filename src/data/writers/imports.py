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
                    # Only treat dotted identifiers as group keys (exclude artifact-only like 'junit')
                    group_keys = {k for k in group_keys if ":" not in k and "." in k}
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
                                (
                                    g.lower().startswith(base.lower())
                                    or base.lower().startswith(g.lower())
                                )
                                for g in group_keys
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

    # Always prepare holders for dependency nodes from imports and from resolved GAVs
    dependency_nodes: list[dict[str, Any]] = []
    gav_nodes: list[dict[str, Any]] = []
    # Deprecated: ExternalDependencyPackage support removed; enforce versioned dependencies only

    if external_dependencies:
        logger.info(f"Creating {len(external_dependencies)} external dependency nodes...")

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
                        if dep.lower().startswith(g.lower()) or g.lower().startswith(dep.lower()):
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

                # Additional targeted mappings for common ecosystems and tricky groups
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
                        # Case/canonicalization fixes
                        ("org.HdrHistogram", ("org.hdrhistogram", "HdrHistogram")),
                        ("org.opentest4j", ("org.opentest4j", "opentest4j")),
                        ("org.junitpioneer", ("org.junit-pioneer", "junit-pioneer")),
                        ("org.s1ck.gdl", ("org.s1ck", "gdl")),
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

            # If Jackson generic package, emit nodes only for artifacts with known versions to avoid overwriting
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
                    if v is not None:
                        jackson_variants.append(
                            {
                                "package": dep,
                                "language": "java",
                                "ecosystem": "maven",
                                "group_id": g,
                                "artifact_id": art,
                                "version": v,
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

                dependency_nodes.append(dependency_node)

    # Systemic: always create/merge nodes directly from resolved GAV entries
    if dep_versions:
        for k, v in dep_versions.items():
            if ":" in k and len(k.split(":")) == 3:
                g, a, ver = str(k).split(":")
                gav_nodes.append(
                    {
                        "package": g,  # base package as group id
                        "group_id": g,
                        "artifact_id": a,
                        "version": v,
                        "language": "java",
                        "ecosystem": "maven",
                    }
                )

    if dependency_nodes:
        # Fail fast if any GAV coordinate is missing a version per project policy
        missing_versions = [
            dep
            for dep in dependency_nodes
            if dep.get("group_id") and dep.get("artifact_id") and not dep.get("version")
        ]
        if missing_versions:
            sample = missing_versions[:5]
            details = ", ".join(
                f"{d.get('group_id')}:{d.get('artifact_id')} (package={d.get('package')})"
                for d in sample
            )
            more = " ..." if len(missing_versions) > 5 else ""
            from os import getenv as _getenv  # local import to avoid global dependency

            used_flag = _getenv("RESOLVE_BUILD_DEPS") in {"1", "true", "True"}
            if used_flag:
                guidance = (
                    "\nDependency resolution failed: some GAV coordinates still lack versions after build resolution.\n"
                    f"Missing versions for: {details}{more}\n\n"
                    "Next steps:\n"
                    "- Ensure the repo's build can produce a full dependency report (try ./gradlew dependencies and mvnw dependency:list).\n"
                    "- If the types are transitives (e.g., opentest4j via junit), add an override JSON and pass via --in-dependencies.\n"
                    "- Verify Gradle lockfiles or Maven dependencyManagement/BOM are present and committed.\n"
                )
            else:
                guidance = (
                    "\nDependency resolution failed: some GAV coordinates have no version.\n"
                    f"Missing versions for: {details}{more}\n\n"
                    "How to fix:\n"
                    "- Re-run with build resolution to capture full versions (includes test/transitives):\n"
                    "    code-graph-pipeline-prefect --repo-url <REPO> --resolve-build-deps\n"
                    "  or, if running code_analysis directly, provide a dependencies JSON via --in-dependencies.\n"
                    "- Alternatively, ensure your dependency extraction includes dependencyManagement/BOM and lockfiles.\n"
                )
            raise ValueError(guidance)
        session.run(
            """
            UNWIND $dependencies AS dep
            WITH dep
            FOREACH (_ IN CASE WHEN dep.group_id IS NOT NULL AND dep.artifact_id IS NOT NULL AND dep.version IS NOT NULL THEN [1] ELSE [] END |
              MERGE (e:ExternalDependency {group_id: dep.group_id, artifact_id: dep.artifact_id, version: dep.version})
              SET e.language = coalesce(e.language, dep.language),
                  e.ecosystem = coalesce(e.ecosystem, dep.ecosystem),
                  e.package = coalesce(e.package, dep.package)
            )
            // When only package and a concrete version are known, still create a versioned
            // ExternalDependency node to support AFFECTS linking and idempotent counts.
            FOREACH (_ IN CASE WHEN (dep.group_id IS NULL OR dep.artifact_id IS NULL) AND dep.version IS NOT NULL THEN [1] ELSE [] END |
              MERGE (e:ExternalDependency {package: dep.package, version: dep.version})
              SET e.language = coalesce(e.language, dep.language),
                  e.ecosystem = coalesce(e.ecosystem, dep.ecosystem)
            )

            """,
            dependencies=dependency_nodes,
        )

    if gav_nodes:
        # Create or match nodes on precise coordinates to avoid duplicates across versions
        session.run(
            """
            UNWIND $gavs AS dep
            MERGE (e:ExternalDependency {group_id: dep.group_id, artifact_id: dep.artifact_id, version: dep.version})
            SET e.language = coalesce(e.language, dep.language),
                e.ecosystem = coalesce(e.ecosystem, dep.ecosystem),
                e.package = coalesce(e.package, dep.package)
            """,
            gavs=gav_nodes,
        )

    # Join imports to versioned ExternalDependency via best-effort GAV or package match
    session.run(
        """
        MATCH (i:Import)
        WHERE i.import_type = 'external'
        WITH i, SPLIT(i.import_path, '.') AS parts
        WITH i,
             CASE WHEN SIZE(parts) >= 4 THEN parts[0]+'.'+parts[1]+'.'+parts[2]+'.'+parts[3] ELSE NULL END AS p4,
             CASE WHEN SIZE(parts) >= 3 THEN parts[0]+'.'+parts[1]+'.'+parts[2] ELSE NULL END AS p3,
             CASE WHEN SIZE(parts) >= 2 THEN parts[0]+'.'+parts[1] ELSE NULL END AS p2
        OPTIONAL MATCH (e:ExternalDependency)
        WHERE (e.group_id IS NOT NULL AND e.group_id IN [p4, p3, p2])
           OR (e.package IS NOT NULL AND e.package IN [p4, p3, p2])
        WITH i, collect(DISTINCT e) AS eds, p4, p3, p2
        FOREACH (ed IN eds |
          MERGE (i)-[:DEPENDS_ON]->(ed)
        )
        """
    )

    # Fail fast if any external import could not be linked to a versioned dependency
    rec = session.run(
        """
        MATCH (i:Import {import_type:'external'})
        OPTIONAL MATCH (i)-[:DEPENDS_ON]->(e:ExternalDependency)
        WITH i, count(e) AS c
        WHERE c = 0
        RETURN collect(i.import_path) AS missing
        """
    ).single()
    if rec and rec.get("missing"):
        missing = rec["missing"]
        sample = missing[:5]
        details = ", ".join(sample)
        more = " ..." if len(missing) > 5 else ""
        guidance = (
            "\nUnresolved external imports: no versioned ExternalDependency could be linked.\n"
            f"Missing: {details}{more}\n\n"
            "How to fix:\n"
            "- Re-run with build resolution to obtain concrete versions (transitives/test scope):\n"
            "    code-graph-pipeline-prefect --repo-url <REPO> --resolve-build-deps\n"
            "  or supply a curated dependencies JSON via --in-dependencies.\n"
            "- Ensure imported packages map deterministically to versioned dependencies.\n"
        )
        raise ValueError(guidance)
