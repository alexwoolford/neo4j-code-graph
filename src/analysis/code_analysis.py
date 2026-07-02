#!/usr/bin/env python3
from __future__ import annotations

import logging
import re
import tempfile
import xml.etree.ElementTree as ET
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any

# FileData typing removed to avoid mypy redefinition; use dict[str, Any] locally where needed

try:
    _extractor = import_module("src.analysis.extractor")
except Exception:  # pragma: no cover - installed package execution path
    _extractor = import_module("analysis.extractor")

extract_files_concurrently = _extractor.extract_files_concurrently
list_java_files = _extractor.list_java_files

try:
    parse_args = import_module("src.analysis.cli").parse_args  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    parse_args = import_module("analysis.cli").parse_args  # type: ignore[attr-defined]

try:
    setup_logging = import_module("src.utils.common").setup_logging  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    setup_logging = import_module("utils.common").setup_logging  # type: ignore[attr-defined]

# Constants for method call parsing
JAVA_KEYWORDS_TO_SKIP = {
    "i",
    "while",
    "for",
    "switch",
    "catch",
    "synchronized",
    "return",
    "throw",
    "new",
    "assert",
    "super",
    "this",
}

logger = logging.getLogger(__name__)

# Module-level default for quiet parse flag, set by main() based on CLI args
_QUIET_PARSE: bool = False


def extract_dependency_versions_from_files(repo_root: Path) -> dict[str, str]:
    """Extract dependency versions from pom.xml, build.gradle, and other dependency files.

    Scans the repository for dependency management files (Maven, Gradle, SBT) and extracts
    dependency name-version mappings to enable accurate CVE analysis.

    Args:
        repo_root (Path): Root directory of the repository to scan

    Returns:
        dict: Mapping of dependency names to their versions

    Example:
        >>> versions = extract_dependency_versions_from_files(Path("/path/to/repo"))
        >>> print(versions)
        {'org.apache.commons:commons-lang3': '3.12.0', 'junit:junit': '4.13.2'}
    """
    logger.info("🔍 Scanning for dependency management files...")
    dependency_versions: dict[str, str] = {}

    # Find Maven pom.xml files
    for pom_file in repo_root.rglob("pom.xml"):
        try:
            logger.debug(f"Processing Maven file: {pom_file}")
            versions = _extract_maven_dependencies(pom_file)
            dependency_versions.update(versions)
        except Exception as e:
            logger.debug(f"Error processing {pom_file}: {e}")

    # Find Gradle build files
    for gradle_file in repo_root.rglob("build.gradle*"):
        try:
            logger.debug(f"Processing Gradle file: {gradle_file}")
            versions = extract_gradle_dependencies(gradle_file)
            dependency_versions.update(versions)
        except Exception as e:
            logger.debug(f"Error processing {gradle_file}: {e}")

    logger.info(f"📊 Found version information for {len(dependency_versions)} dependencies")
    return dependency_versions


def _extract_maven_dependencies(pom_file: Path) -> dict[str, str]:
    """Extract dependency versions from Maven pom.xml file."""
    dependency_versions: dict[str, str] = {}

    try:
        tree = ET.parse(pom_file)
        root = tree.getroot()

        # Handle namespaces
        namespace = {"maven": "http://maven.apache.org/POM/4.0.0"}
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0][1:]
            namespace = {"maven": ns}

        # Extract dependencies
        for dependency in root.findall(".//maven:dependency", namespace):
            group_id_elem = dependency.find("maven:groupId", namespace)
            artifact_id_elem = dependency.find("maven:artifactId", namespace)
            version_elem = dependency.find("maven:version", namespace)

            if (
                group_id_elem is not None
                and artifact_id_elem is not None
                and version_elem is not None
            ):
                group_id = group_id_elem.text
                artifact_id = artifact_id_elem.text
                version = version_elem.text

                # Create package name matching our import logic
                package_name = f"{group_id}.{artifact_id}"

                # Handle version properties (like ${spring.version})
                if version and version.startswith("${") and version.endswith("}"):
                    # Try to resolve from properties
                    prop_name = version[2:-1]
                    prop_elem = root.find(f".//maven:properties/maven:{prop_name}", namespace)
                    if prop_elem is not None:
                        version = prop_elem.text

                if version and not version.startswith("${"):
                    dependency_versions[package_name] = version
                    # Also store full GAV key to enable precise matching later
                    dependency_versions[f"{group_id}:{artifact_id}:{version}"] = version
                    logger.debug(
                        f"Found Maven dependency: {package_name} -> {version} (GAV {group_id}:{artifact_id}:{version})"
                    )

        # Also check for common groupIds in dependencies
        for dependency in root.findall(".//maven:dependency", namespace):
            group_id_elem = dependency.find("maven:groupId", namespace)
            if group_id_elem is not None:
                group_id = group_id_elem.text
                # Add just the group as well for broader matching
                if group_id not in dependency_versions:
                    version_elem = dependency.find("maven:version", namespace)
                    if version_elem is not None:
                        version = version_elem.text
                        if version and not version.startswith("${"):
                            dependency_versions[group_id] = version

    except ET.ParseError as e:
        logger.debug(f"XML parsing error in {pom_file}: {e}")
    except Exception as e:
        logger.debug(f"Error processing Maven file {pom_file}: {e}")

    return dependency_versions


def extract_gradle_dependencies(gradle_file: Path) -> dict[str, str]:
    """Extract dependency versions from Gradle build files."""
    dependency_versions: dict[str, str] = {}

    try:
        with open(gradle_file, encoding="utf-8") as f:
            content = f.read()

        # Regex patterns capturing groupId, artifactId and version
        patterns = [
            # implementation 'group:artifact:version'
            (
                r"(?:implementation|api|compile|testImplementation|testCompile|runtime)\s+[\"']"
                r"([a-zA-Z0-9._-]+):([a-zA-Z0-9._-]+):([^\"'\s]+)[\"']"
            ),
            # implementation group: 'group', name: 'artifact', version: '1.0.0'
            (
                r"(?:implementation|api|compile|testImplementation|testCompile|runtime)\s+.*?"
                r"group\s*[:=]\s*[\"']([a-zA-Z0-9._-]+)[\"'].*?"
                r"name\s*[:=]\s*[\"']([a-zA-Z0-9._-]+)[\"'].*?"
                r"version\s*[:=]\s*[\"']([^\"']+)[\"']"
            ),
        ]
        for pattern in patterns:
            matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
            for match in matches:
                if len(match.groups()) != 3 or None in match.groups():
                    continue
                group_id, artifact_id, version = match.groups()
                package_name = f"{group_id}.{artifact_id}"

                # Skip version variables for now
                if not version.startswith("$"):
                    dependency_versions[package_name] = version
                    dependency_versions[group_id] = version  # Also add group for broader matching
                    # Also store full GAV key to enable precise matching later
                    dependency_versions[f"{group_id}:{artifact_id}:{version}"] = version
                    logger.debug(
                        f"Found Gradle dependency: {package_name} -> {version} (GAV {group_id}:{artifact_id}:{version})"
                    )

        # Also look for version catalogs and properties
        version_props = re.finditer(r"(\w+Version)\s*=\s*['\"]([^'\"]+)['\"]", content)
        prop_to_version = {}
        for match in version_props:
            prop_name, version = match.groups()
            prop_to_version[prop_name] = version

        # Try to resolve version references
        for package, version in list(dependency_versions.items()):
            if version in prop_to_version:
                dependency_versions[package] = prop_to_version[version]

    except Exception as e:
        logger.debug(f"Error processing Gradle file {gradle_file}: {e}")

    return dependency_versions


# Backward-compatible private alias for tests that may import the old name
_extract_gradle_dependencies = extract_gradle_dependencies


try:
    extract_file_data = import_module("src.analysis.parser").extract_file_data  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    extract_file_data = import_module("analysis.parser").extract_file_data  # type: ignore[attr-defined]

try:
    _writer = import_module("src.data.graph_writer")
except Exception:  # pragma: no cover
    _writer = import_module("data.graph_writer")
bulk_create_nodes_and_relationships = _writer.bulk_create_nodes_and_relationships  # noqa: F401
create_classes = _writer.create_classes  # noqa: F401
create_directories = _writer.create_directories  # noqa: F401
create_files = _writer.create_files  # noqa: F401
create_imports = _writer.create_imports  # noqa: F401
create_method_calls = _writer.create_method_calls  # noqa: F401
create_methods = _writer.create_methods  # noqa: F401

# Re-exported: create_files, create_directories, create_classes (imported above)


## writer functions imported from src.data.graph_writer (see imports above)


## bulk_create_nodes_and_relationships is re-exported from data.graph_writer

# Back-compat re-export for tests expecting batching helper here
try:
    _batching = import_module("src.utils.batching")
except Exception:  # pragma: no cover
    try:
        _batching = import_module("utils.batching")
    except Exception:  # pragma: no cover
        _batching = None

if _batching is not None:

    def get_database_batch_size(
        has_embeddings: bool = False, estimated_size_mb: int | None = None
    ) -> int:
        return _batching.get_database_batch_size(
            has_embeddings=has_embeddings, estimated_size_mb=estimated_size_mb
        )


def main():
    """Main function."""
    from pathlib import Path as _Path

    args = parse_args()

    setup_logging(args.log_level, args.log_file)
    # Control per-file parse logging noise
    global _QUIET_PARSE
    _QUIET_PARSE = bool(getattr(args, "quiet_parse", False))

    # Resolve repository path (clone if URL)
    repo_path = Path(args.repo_url)
    if repo_path.exists() and repo_path.is_dir():
        logger.info("Using local repository: %s", args.repo_url)
        repo_root = repo_path
        tmpdir = None
    else:
        tmpdir = tempfile.mkdtemp()
        logger.info("Cloning %s...", args.repo_url)
        import git

        git.Repo.clone_from(args.repo_url, tmpdir)
        repo_root = Path(tmpdir)

    java_files = list_java_files(repo_root)
    logger.info("Found %d Java files to process", len(java_files))

    # Dependency extraction (allow artifact in/out)
    dependency_versions: dict[str, str] = {}
    if (
        getattr(args, "in_dependencies", None)
        and args.in_dependencies
        and _Path(args.in_dependencies).exists()
    ):
        try:
            load_dependencies_from_json = import_module(
                "src.analysis.io"
            ).load_dependencies_from_json  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            load_dependencies_from_json = import_module("analysis.io").load_dependencies_from_json  # type: ignore[attr-defined]

        logger.info("Reading dependencies from %s", args.in_dependencies)
        dependency_versions = load_dependencies_from_json(_Path(args.in_dependencies))
    else:
        # Always use the enhanced extractor. No silent fallback to the basic scanner.
        try:
            extract_enhanced_dependencies_for_neo4j = import_module(
                "src.analysis.dependency_extraction"
            ).extract_enhanced_dependencies_for_neo4j  # type: ignore[attr-defined]
        except Exception:
            try:
                extract_enhanced_dependencies_for_neo4j = import_module(
                    "analysis.dependency_extraction"
                ).extract_enhanced_dependencies_for_neo4j  # type: ignore[attr-defined]
            except Exception as e:
                logger.error("Enhanced dependency extractor unavailable: %s", e)
                raise SystemExit(2) from e

        try:
            dependency_versions = extract_enhanced_dependencies_for_neo4j(repo_root)
            logger.info(
                "🚀 Using enhanced dependency extraction: %d dependency keys",
                len(dependency_versions),
            )
        except Exception as e:
            logger.error("Enhanced dependency extraction failed: %s", e)
            raise SystemExit(2) from e

        # Fail fast if build files are present but no dependency keys were resolved
        try:
            has_maven = any(repo_root.rglob("pom.xml"))
            has_gradle_build = any(repo_root.rglob("build.gradle*"))
            has_gradle_lock = (repo_root / "gradle.lockfile").exists()
            has_version_catalog = (repo_root / "libs.versions.toml").exists() or any(
                (repo_root / "gradle").glob("*.toml")
            )
            build_files_present = (
                has_maven or has_gradle_build or has_gradle_lock or has_version_catalog
            )
        except Exception:
            build_files_present = False

        logger.info("📦 Dependency keys available for ingest: %d", len(dependency_versions))
        if build_files_present and not dependency_versions:
            logger.error(
                "Build files were detected (Maven/Gradle) but zero dependency versions were extracted. Failing fast per policy to avoid silent fallbacks."
            )
            raise SystemExit(2)
        if getattr(args, "out_dependencies", None) and args.out_dependencies:
            try:
                save_dependencies_to_json = import_module(
                    "src.analysis.io"
                ).save_dependencies_to_json  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                save_dependencies_to_json = import_module("analysis.io").save_dependencies_to_json  # type: ignore[attr-defined]

            save_dependencies_to_json(_Path(args.out_dependencies), dependency_versions)

    # Phase 1: Extract file data (allow artifact in/out)
    logger.info("Phase 1: Extracting file data...")
    start_phase1 = perf_counter()

    files_data: list[dict[str, Any]] = []
    if (
        getattr(args, "in_files_data", None)
        and args.in_files_data
        and _Path(args.in_files_data).exists()
    ):
        try:
            read_files_data = import_module("src.analysis.io").read_files_data  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            read_files_data = import_module("analysis.io").read_files_data  # type: ignore[attr-defined]

        logger.info("Reading files data from %s", args.in_files_data)
        files_data = read_files_data(_Path(args.in_files_data))
    else:
        # Skip DB lookup to avoid coupling extract-only runs to Neo4j
        files_to_process = list(java_files)
        logger.info("Processing %d files", len(files_to_process))
        files_data, parse_errors = extract_files_concurrently(
            files_to_process, repo_root, extract_file_data, args.parallel_files
        )

        # Persist parse errors summary if requested
        if parse_errors:
            if args.parse_errors_file:
                out_path = _Path(args.parse_errors_file)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    "\n".join(f"{p}\t{err}" for p, err in parse_errors), encoding="utf-8"
                )
                logger.warning(
                    "Java parse: %d errors. Details: %s",
                    len(parse_errors),
                    out_path,
                )
            else:
                logger.warning(
                    "Java parse: %d errors. Use --parse-errors-file to capture details",
                    len(parse_errors),
                )

        if getattr(args, "out_files_data", None) and args.out_files_data:
            try:
                write_files_data = import_module("src.analysis.io").write_files_data  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                write_files_data = import_module("analysis.io").write_files_data  # type: ignore[attr-defined]

            write_files_data(_Path(args.out_files_data), files_data)

    phase1_time = perf_counter() - start_phase1
    logger.info("Phase 1 completed in %.2fs", phase1_time)

    # Phase 2: Write to Neo4j
    if getattr(args, "skip_db", False):
        logger.info("Phase 2: Skipped (--skip-db)")
        logger.info(
            "TOTAL: Processed %d files in %.2fs (%.2f files/sec)",
            len(files_data),
            phase1_time,
            len(files_data) / max(phase1_time, 1e-6),
        )
        if tmpdir:
            import shutil as _shutil

            _shutil.rmtree(tmpdir, ignore_errors=True)
            logger.info("Cleaned up temporary repository clone")
        return

    logger.info("Phase 2: Creating graph in Neo4j...")
    start_phase2 = perf_counter()
    try:
        _create_driver = import_module("src.utils.common").create_neo4j_driver  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        _create_driver = import_module("utils.common").create_neo4j_driver  # type: ignore[attr-defined]

    with _create_driver(args.uri, args.username, args.password) as driver:
        with driver.session(database=args.database) as session:  # type: ignore[reportUnknownMemberType]
            try:
                # Ensure required constraints exist before any writes
                try:
                    _ensure = import_module(
                        "src.data.schema_management"
                    ).ensure_constraints_exist_or_fail  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    _ensure = import_module(
                        "data.schema_management"
                    ).ensure_constraints_exist_or_fail  # type: ignore[attr-defined]

                _ensure(session)  # type: ignore[misc]
            except Exception as _e:
                logger.error("Constraints check failed: %s", _e)
                raise
            if files_data:
                bulk_create_nodes_and_relationships(
                    session,
                    files_data,
                    dependency_versions=dependency_versions,
                )
            else:
                logger.info("No new files to process - skipping bulk creation")

    phase2_time = perf_counter() - start_phase2
    logger.info("Phase 2 completed in %.2fs", phase2_time)

    total_time = phase1_time + phase2_time
    logger.info(
        "TOTAL: Processed %d files in %.2fs (%.2f files/sec)",
        len(files_data),
        total_time,
        len(files_data) / max(total_time, 1e-6),
    )
    logger.info(
        "Phase breakdown: Extract=%.1fs, Database=%.1fs",
        phase1_time,
        phase2_time,
    )

    if tmpdir:
        import shutil as _shutil

        _shutil.rmtree(tmpdir, ignore_errors=True)
        logger.info("Cleaned up temporary repository clone")


if __name__ == "__main__":
    main()
