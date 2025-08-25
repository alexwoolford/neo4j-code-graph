#!/usr/bin/env python3

import gc
import logging
import re
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import Any

try:
    from src.analysis.types import FileData
except Exception:
    FileData = dict  # type: ignore[misc,assignment]

from tqdm import tqdm

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
    DB_BATCH_SIMPLE,
    DB_BATCH_WITH_EMBEDDINGS,
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


def build_method_signature(
    package_name: str | None,
    class_name: str | None,
    method_name: str,
    parameters: list,
    return_type: str | None,
) -> str:
    """Build a stable method signature string for uniqueness and Bloom captions.

    Format: <package>.<class>#<method>(<paramType,...>):<returnType>
    Missing parts are omitted gracefully.
    """
    pkg = f"{package_name}." if package_name else ""
    cls = class_name or ""
    param_types = []
    for p in parameters or []:
        # parameters are {name, type}
        t = p.get("type") if isinstance(p, dict) else None
        param_types.append(str(t) if t is not None else "?")
    params_str = ",".join(param_types)
    ret = return_type or "void"
    if cls:
        return f"{pkg}{cls}#{method_name}({params_str}):{ret}"
    # Fallback without class
    return f"{pkg}{method_name}({params_str}):{ret}"


def get_database_batch_size(
    has_embeddings: bool = False, estimated_size_mb: int | None = None
) -> int:
    """
    Determine optimal batch size for database operations.

    Args:
        has_embeddings: Whether the data includes large embedding vectors
        estimated_size_mb: Estimated size per item in MB

    Returns:
        Optimal batch size for Neo4j operations
    """
    if has_embeddings:
        return DB_BATCH_WITH_EMBEDDINGS
    elif estimated_size_mb and estimated_size_mb > 1:
        # Large data items - reduce batch size
        return 500
    else:
        # Standard batch size for simple operations
        return DB_BATCH_SIMPLE


# compute_embeddings_bulk is imported from analysis.embeddings


def extract_file_data(file_path: Path, repo_root: Path):
    """Extract all data from a single Java file using Tree-sitter (primary parser).

    Delegates to `java_treesitter.extract_file_data` and preserves the output
    structure expected by downstream writers. On failure, returns a minimal
    payload so the caller can continue gracefully.
    """
    try:
        from src.analysis import java_treesitter as _jt  # type: ignore
    except Exception:
        _jt = None  # type: ignore

    if _jt is not None and hasattr(_jt, "extract_file_data"):
        try:
            return _jt.extract_file_data(file_path, repo_root)
        except Exception as e:  # pragma: no cover - unexpected parse failure
            rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
            logger.warning("Tree-sitter failed for %s: %s", rel_path, e)
            try:
                PARSE_ERRORS.append((rel_path, str(e)))
            except Exception:
                pass
            return {
                "path": rel_path,
                "code": "",
                "methods": [],
                "classes": [],
                "interfaces": [],
                "imports": [],
                "language": "java",
                "ecosystem": "maven",
                "total_lines": 0,
                "code_lines": 0,
                "method_count": 0,
                "class_count": 0,
                "interface_count": 0,
            }

    # If Tree-sitter module is unavailable, return a minimal structure
    rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
    logger.warning("Tree-sitter extractor not available; skipping %s", rel_path)
    try:
        PARSE_ERRORS.append((rel_path, "treesitter_unavailable"))
    except Exception:
        pass
    return {
        "path": rel_path,
        "code": "",
        "methods": [],
        "classes": [],
        "interfaces": [],
        "imports": [],
        "language": "java",
        "ecosystem": "maven",
        "total_lines": 0,
        "code_lines": 0,
        "method_count": 0,
        "class_count": 0,
        "interface_count": 0,
    }


def _extract_method_calls(method_code, containing_class):
    """
    Extract method calls from Java method code using regex patterns.

    This handles common Java method invocation patterns:
    - object.method()
    - this.method()
    - super.method()
    - ClassName.staticMethod()
    - method() (same class)
    """
    if not method_code:
        return []

    method_calls = []

    try:
        # Pattern to match method calls: word.methodName() or just methodName()
        # This covers: obj.method(), this.method(), super.method(), Class.staticMethod(), method()
        call_pattern = r"(?:(\w+)\.)?(\w+)\s*\("

        # Find all matches
        matches = re.finditer(call_pattern, method_code)

        for match in matches:
            qualifier = match.group(1)  # The part before the dot (could be None)
            method_name = match.group(2)

            # Skip common Java keywords and operators that match the pattern
            if method_name.lower() in JAVA_KEYWORDS_TO_SKIP:
                continue

            # Skip obvious constructors (capitalized method names)
            if method_name[0].isupper():
                continue

            # Determine target class and call type based on qualifier
            target_class, call_type = _determine_call_target(qualifier, containing_class)

            method_calls.append(
                {
                    "method_name": method_name,
                    "target_class": target_class,
                    "qualifier": qualifier,
                    "call_type": call_type,
                }
            )

    except Exception as e:
        # Log but don't fail on parsing errors
        logger.debug(f"Error parsing method calls in {containing_class}: {e}")

    return method_calls


def _determine_call_target(qualifier, containing_class):
    """Determine the target class and call type for a method call."""
    if qualifier is None:
        # Direct method call - assume same class
        return containing_class, "same_class"
    elif qualifier == "this":
        return containing_class, "this"
    elif qualifier == "super":
        return "super", "super"  # We'll resolve inheritance later
    elif qualifier[0].isupper():
        # Capitalized qualifier likely a class name (static call)
        return qualifier, "static"
    else:
        # Lowercase qualifier likely an object instance
        return qualifier, "instance"  # We'll resolve the type later if possible


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


def main():
    """Main function."""
    import json
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

    java_files = list(repo_root.rglob("*.java"))
    logger.info("Found %d Java files to process", len(java_files))

    # Dependency extraction (allow artifact in/out)
    dependency_versions: dict[str, str] = {}
    if (
        getattr(args, "in_dependencies", None)
        and args.in_dependencies
        and _Path(args.in_dependencies).exists()
    ):
        logger.info("Reading dependencies from %s", args.in_dependencies)
        dependency_versions = json.loads(_Path(args.in_dependencies).read_text(encoding="utf-8"))
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
            _Path(args.out_dependencies).parent.mkdir(parents=True, exist_ok=True)
            _Path(args.out_dependencies).write_text(
                json.dumps(dependency_versions, ensure_ascii=False), encoding="utf-8"
            )

    # Phase 1: Extract file data (allow artifact in/out)
    logger.info("Phase 1: Extracting file data...")
    start_phase1 = perf_counter()

    files_data: list[FileData] = []  # type: ignore[assignment]
    if (
        getattr(args, "in_files_data", None)
        and args.in_files_data
        and _Path(args.in_files_data).exists()
    ):
        logger.info("Reading files data from %s", args.in_files_data)
        files_data = json.loads(_Path(args.in_files_data).read_text(encoding="utf-8"))
    else:
        # Skip DB lookup to avoid coupling extract-only runs to Neo4j
        files_to_process = list(java_files)
        logger.info("Processing %d files", len(files_to_process))
        if files_to_process:
            with ThreadPoolExecutor(max_workers=args.parallel_files) as executor:
                future_to_file = {
                    executor.submit(extract_file_data, file_path, repo_root): file_path
                    for file_path in files_to_process
                }
                for future in tqdm(
                    as_completed(future_to_file),
                    total=len(files_to_process),
                    desc="Extracting files",
                ):
                    result = future.result()
                    if result:
                        files_data.append(result)  # type: ignore[arg-type]

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
            _Path(args.out_files_data).parent.mkdir(parents=True, exist_ok=True)
            _Path(args.out_files_data).write_text(
                json.dumps(files_data, ensure_ascii=False), encoding="utf-8"
            )

    phase1_time = perf_counter() - start_phase1
    logger.info("Phase 1 completed in %.2fs", phase1_time)

    # Phase 2: Compute embeddings (allow artifact in/out and target selection)
    logger.info("Phase 2: Computing embeddings...")
    start_phase2 = perf_counter()

    file_embeddings: list[list[float]] = []
    method_embeddings: list[list[float]] = []

    def _np():  # lazy numpy import
        import numpy as _numpy  # type: ignore

        return _numpy

    # Always attempt to read provided embeddings artifacts first
    files_loaded = False
    methods_loaded = False
    if (
        getattr(args, "in_file_embeddings", None)
        and args.in_file_embeddings
        and _Path(args.in_file_embeddings).exists()
    ):
        try:
            # Keep as numpy array to avoid expensive upfront Python list conversion
            file_embeddings = _np().load(args.in_file_embeddings, allow_pickle=False)
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
            # Keep as numpy array to avoid expensive upfront Python list conversion
            method_embeddings = _np().load(args.in_method_embeddings, allow_pickle=False)
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
        _Path(args.out_file_embeddings).parent.mkdir(parents=True, exist_ok=True)
        _np().save(args.out_file_embeddings, _np().array(file_embeddings, dtype="float32"))
        logger.info("Wrote file embeddings to %s", args.out_file_embeddings)
    if (
        getattr(args, "out_method_embeddings", None)
        and args.out_method_embeddings
        and method_embeddings
    ):
        _Path(args.out_method_embeddings).parent.mkdir(parents=True, exist_ok=True)
        _np().save(args.out_method_embeddings, _np().array(method_embeddings, dtype="float32"))
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
