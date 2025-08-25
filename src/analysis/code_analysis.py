#!/usr/bin/env python3

import gc
import logging
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from time import perf_counter
from typing import Any

try:
    from src.analysis.types import FileData
except Exception:
    FileData = dict  # type: ignore[misc,assignment]

from src.analysis.extractor import extract_files_concurrently, list_java_files

# Collect Java parse errors across threads to summarize later
PARSE_ERRORS: list[tuple[str, str]] = []

from src.analysis.cli import parse_args
from src.analysis.embeddings import compute_embeddings_bulk
from src.utils.common import setup_logging

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

from src.constants import (
    DEFAULT_EMBED_BATCH_CPU,
    DEFAULT_EMBED_BATCH_CUDA_LARGE,
    DEFAULT_EMBED_BATCH_CUDA_SMALL,
    DEFAULT_EMBED_BATCH_CUDA_VERY_LARGE,
    DEFAULT_EMBED_BATCH_MPS,
    MODEL_NAME,
)


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
            versions = _extract_gradle_dependencies(gradle_file)
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


def _extract_gradle_dependencies(gradle_file: Path) -> dict[str, str]:
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


def get_device() -> Any:
    """Get the appropriate device for PyTorch computations."""
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    else:
        return torch.device("cpu")


def load_model_and_tokenizer() -> tuple[Any, Any, Any, int]:
    """Load the embedding model and tokenizer for embedding computation."""
    from transformers import AutoModel, AutoTokenizer

    logger.info("Loading embedding model: %s", MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME)
    device = get_device()

    # Optimize for MPS performance
    if device.type == "mps":
        # Enable high memory usage mode for better performance
        import os

        os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
        logger.info("Enabled MPS high performance mode")

    model = model.to(device)
    logger.info(f"Model loaded on {device}")

    # Get optimal batch size
    batch_size = get_optimal_batch_size(device)
    logger.info(f"Using batch size: {batch_size}")

    return tokenizer, model, device, batch_size


def get_optimal_batch_size(device: Any) -> int:
    """Determine optimal batch size based on device and available memory."""
    import os

    import torch

    if device.type == "cuda":
        gpu_memory = torch.cuda.get_device_properties(0).total_memory
        if gpu_memory > 20 * 1024**3:  # >20GB
            return DEFAULT_EMBED_BATCH_CUDA_VERY_LARGE
        elif gpu_memory > 10 * 1024**3:  # >10GB
            return DEFAULT_EMBED_BATCH_CUDA_LARGE
        else:  # 8GB or less
            return DEFAULT_EMBED_BATCH_CUDA_SMALL
    elif device.type == "mps":
        # Allow override for Apple MPS batch size via env if desired
        try:
            override = int(os.getenv("EMBED_BATCH_MPS", ""))
            if override > 0:
                return override
        except Exception:
            pass
        return DEFAULT_EMBED_BATCH_MPS
    else:
        try:
            override = int(os.getenv("EMBED_BATCH_CPU", ""))
            if override > 0:
                return override
        except Exception:
            pass
        return DEFAULT_EMBED_BATCH_CPU


from src.analysis.calls import (
    _determine_call_target as _determine_call_target,
)
from src.analysis.parser import build_method_signature as build_method_signature  # re-export

# compute_embeddings_bulk is imported from analysis.embeddings
from src.analysis.parser import extract_file_data as extract_file_data  # re-export
from src.data.graph_writer import (  # type: ignore
    bulk_create_nodes_and_relationships,  # noqa: F401 - re-exported for back-compat
    create_classes,  # noqa: F401 - re-exported for back-compat
    create_directories,  # noqa: F401 - re-exported for back-compat
    create_files,  # noqa: F401 - re-exported for back-compat
    create_imports,  # noqa: F401 - re-exported for back-compat
    create_method_calls,  # noqa: F401 - re-exported for back-compat
    create_methods,  # noqa: F401 - re-exported for back-compat
)

# Re-exported: create_files, create_directories, create_classes (imported above)


## writer functions imported from src.data.graph_writer (see imports above)


## bulk_create_nodes_and_relationships is re-exported from data.graph_writer

# Back-compat re-export for tests expecting batching helper here
try:
    from src.utils.batching import get_database_batch_size as _get_db_batch_size

    def get_database_batch_size(
        has_embeddings: bool = False, estimated_size_mb: int | None = None
    ) -> int:
        return _get_db_batch_size(
            has_embeddings=has_embeddings, estimated_size_mb=estimated_size_mb
        )

except Exception:  # pragma: no cover
    pass


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
        from src.analysis.io import load_dependencies_from_json

        logger.info("Reading dependencies from %s", args.in_dependencies)
        dependency_versions = load_dependencies_from_json(_Path(args.in_dependencies))
    else:
        try:
            from src.analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j
        except ImportError:
            extract_enhanced_dependencies_for_neo4j = None  # type: ignore

        if extract_enhanced_dependencies_for_neo4j is not None:
            try:
                dependency_versions = extract_enhanced_dependencies_for_neo4j(repo_root)
                logger.info(
                    "🚀 Using enhanced dependency extraction: %d dependencies",
                    len(dependency_versions),
                )
            except Exception as e:
                logger.warning(
                    "Enhanced dependency extraction failed (%s), using basic extraction", e
                )
        if not dependency_versions:
            dependency_versions = extract_dependency_versions_from_files(repo_root)
        if getattr(args, "out_dependencies", None) and args.out_dependencies:
            from src.analysis.io import save_dependencies_to_json

            save_dependencies_to_json(_Path(args.out_dependencies), dependency_versions)

    # Phase 1: Extract file data (allow artifact in/out)
    logger.info("Phase 1: Extracting file data...")
    start_phase1 = perf_counter()

    files_data: list[FileData] = []  # type: ignore[assignment]
    if (
        getattr(args, "in_files_data", None)
        and args.in_files_data
        and _Path(args.in_files_data).exists()
    ):
        from src.analysis.io import read_files_data

        logger.info("Reading files data from %s", args.in_files_data)
        files_data = read_files_data(_Path(args.in_files_data))
    else:
        # Skip DB lookup to avoid coupling extract-only runs to Neo4j
        files_to_process = list(java_files)
        logger.info("Processing %d files", len(files_to_process))
        files_data = extract_files_concurrently(
            files_to_process, repo_root, extract_file_data, args.parallel_files
        )

        # Persist parse errors summary if requested
        if PARSE_ERRORS:
            if args.parse_errors_file:
                out_path = _Path(args.parse_errors_file)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    "\n".join(f"{p}\t{err}" for p, err in PARSE_ERRORS), encoding="utf-8"
                )
                logger.warning(
                    "Java parse: %d errors. Details: %s",
                    len(PARSE_ERRORS),
                    out_path,
                )
            else:
                logger.warning(
                    "Java parse: %d errors. Use --parse-errors-file to capture details",
                    len(PARSE_ERRORS),
                )

        if getattr(args, "out_files_data", None) and args.out_files_data:
            from src.analysis.io import write_files_data

            write_files_data(_Path(args.out_files_data), files_data)

    phase1_time = perf_counter() - start_phase1
    logger.info("Phase 1 completed in %.2fs", phase1_time)

    # Phase 2: Compute embeddings (allow artifact in/out and target selection)
    logger.info("Phase 2: Computing embeddings...")
    start_phase2 = perf_counter()

    file_embeddings: list[list[float]] = []
    method_embeddings: list[list[float]] = []

    # removed lazy numpy helper; IO helpers load embeddings when needed

    # Always attempt to read provided embeddings artifacts first
    files_loaded = False
    methods_loaded = False
    if (
        getattr(args, "in_file_embeddings", None)
        and args.in_file_embeddings
        and _Path(args.in_file_embeddings).exists()
    ):
        try:
            from src.analysis.io import load_embeddings

            file_embeddings = load_embeddings(_Path(args.in_file_embeddings))
            files_loaded = True
            logger.info("Loaded file embeddings from %s", args.in_file_embeddings)
        except Exception:
            files_loaded = False
    if (
        getattr(args, "in_method_embeddings", None)
        and args.in_method_embeddings
        and _Path(args.in_method_embeddings).exists()
    ):
        try:
            from src.analysis.io import load_embeddings

            method_embeddings = load_embeddings(_Path(args.in_method_embeddings))
            methods_loaded = True
            logger.info("Loaded method embeddings from %s", args.in_method_embeddings)
        except Exception:
            methods_loaded = False

    need_files = args.embed_target in ("files", "both") and not files_loaded
    need_methods = args.embed_target in ("methods", "both") and not methods_loaded

    # Only compute if not skipping embed and there is work to do
    if not getattr(args, "skip_embed", False) and (need_files or need_methods) and files_data:
        from transformers import AutoModel, AutoTokenizer

        logger.info("Loading embedding model: %s", MODEL_NAME)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME)
        device = get_device()

        if device.type == "mps":
            import os as _os

            _os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
            logger.info("Enabled MPS high performance mode")

        model = model.to(device)
        logger.info(f"Model loaded on {device}")

        batch_size = args.batch_size if args.batch_size else get_optimal_batch_size(device)
        logger.info(f"Using batch size: {batch_size}")

        if need_files:
            file_snippets = [file_data["code"] for file_data in files_data]
            file_embeddings = compute_embeddings_bulk(
                file_snippets, tokenizer, model, device, batch_size
            )
        if need_methods:
            # Single pass over all methods to avoid confusing nested batch logs
            method_snippets = [
                method["code"] for file_data in files_data for method in file_data["methods"]
            ]
            method_embeddings = compute_embeddings_bulk(
                method_snippets, tokenizer, model, device, batch_size
            )

        del model, tokenizer
        try:
            import torch as _torch  # type: ignore

            if device.type == "cuda":
                _torch.cuda.empty_cache()
            elif device.type == "mps":
                _torch.mps.empty_cache()
        except Exception:
            pass
        gc.collect()

    # Persist artifacts if requested
    if getattr(args, "out_file_embeddings", None) and args.out_file_embeddings and file_embeddings:
        from src.analysis.io import save_embeddings

        save_embeddings(_Path(args.out_file_embeddings), file_embeddings)  # type: ignore[arg-type]
        logger.info("Wrote file embeddings to %s", args.out_file_embeddings)
    if (
        getattr(args, "out_method_embeddings", None)
        and args.out_method_embeddings
        and method_embeddings
    ):
        from src.analysis.io import save_embeddings

        save_embeddings(_Path(args.out_method_embeddings), method_embeddings)  # type: ignore[arg-type]
        logger.info("Wrote method embeddings to %s", args.out_method_embeddings)

    phase2_time = 0.0 if getattr(args, "skip_embed", False) else (perf_counter() - start_phase2)
    logger.info("Phase 2 completed in %.2fs", phase2_time)

    # Phase 3: Write to Neo4j
    if getattr(args, "skip_db", False):
        logger.info("Phase 3: Skipped (--skip-db)")
        logger.info(
            "TOTAL: Processed %d files in %.2fs (%.2f files/sec)",
            len(files_data),
            phase1_time + phase2_time,
            len(files_data) / max(phase1_time + phase2_time, 1e-6),
        )
        if tmpdir:
            import shutil as _shutil

            _shutil.rmtree(tmpdir, ignore_errors=True)
            logger.info("Cleaned up temporary repository clone")
        return

    logger.info("Phase 3: Creating graph in Neo4j...")
    start_phase3 = perf_counter()
    from src.utils.common import create_neo4j_driver as _create_driver  # type: ignore

    with _create_driver(args.uri, args.username, args.password) as driver:
        with driver.session(database=args.database) as session:  # type: ignore[reportUnknownMemberType]
            try:
                # Ensure required constraints exist before any writes
                from src.data.schema_management import (  # type: ignore
                    ensure_constraints_exist_or_fail as _ensure,
                )

                _ensure(session)
            except Exception as _e:
                logger.error("Constraints check failed: %s", _e)
                raise
            if files_data:
                bulk_create_nodes_and_relationships(
                    session, files_data, file_embeddings, method_embeddings, dependency_versions
                )
            else:
                logger.info("No new files to process - skipping bulk creation")

    phase3_time = perf_counter() - start_phase3
    logger.info("Phase 3 completed in %.2fs", phase3_time)

    total_time = phase1_time + phase2_time + phase3_time
    logger.info(
        "TOTAL: Processed %d files in %.2fs (%.2f files/sec)",
        len(files_data),
        total_time,
        len(files_data) / max(total_time, 1e-6),
    )
    logger.info(
        "Phase breakdown: Extract=%.1fs, Embeddings=%.1fs, Database=%.1fs",
        phase1_time,
        phase2_time,
        phase3_time,
    )

    if tmpdir:
        import shutil as _shutil

        _shutil.rmtree(tmpdir, ignore_errors=True)
        logger.info("Cleaned up temporary repository clone")


if __name__ == "__main__":
    main()
