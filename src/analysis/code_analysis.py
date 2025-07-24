#!/usr/bin/env python3

import argparse
import logging
import tempfile
from pathlib import Path
import time
from time import perf_counter
import gc
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import xml.etree.ElementTree as ET

import torch
import javalang
from transformers import AutoModel, AutoTokenizer
from tqdm import tqdm

try:
    # Try absolute import when called from CLI wrapper
    from utils.common import setup_logging, create_neo4j_driver, add_common_args
except ImportError:
    # Fallback to relative import when used as module
    from ..utils.common import setup_logging, create_neo4j_driver, add_common_args

logger = logging.getLogger(__name__)

MODEL_NAME = "microsoft/graphcodebert-base"
EMBEDDING_TYPE = "graphcodebert"


def extract_dependency_versions_from_files(repo_root):
    """Extract dependency versions from pom.xml, build.gradle, and other dependency files."""
    logger.info("🔍 Scanning for dependency management files...")
    dependency_versions = {}

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


def _extract_maven_dependencies(pom_file):
    """Extract dependency versions from Maven pom.xml file."""
    dependency_versions = {}

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
                    logger.debug(f"Found Maven dependency: {package_name} -> {version}")

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


def _extract_gradle_dependencies(gradle_file):
    """Extract dependency versions from Gradle build files."""
    dependency_versions = {}

    try:
        with open(gradle_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Pattern for Gradle dependencies like: implementation 'group:artifact:version'
        patterns = [
            r"['\"]([a-zA-Z][a-zA-Z0-9_.\\-]+):([a-zA-Z][a-zA-Z0-9_.\\-]+):([^'\"\\s]+)['\"]",
            r"group\s*:\s*['\"]([^'\"]+)['\"].*?name\s*:\s*['\"]([^'\"]+)['\"]"
            r".*?version\s*:\s*['\"]([^'\"]+)['\"]",
            r"group\s*=\s*['\"]([^'\"]+)['\"].*?name\s*=\s*['\"]([^'\"]+)['\"]"
            r".*?version\s*=\s*['\"]([^'\"]+)['\"]",
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
            for match in matches:
                group_id, artifact_id, version = match.groups()
                package_name = f"{group_id}.{artifact_id}"

                # Skip version variables for now
                if not version.startswith("$"):
                    dependency_versions[package_name] = version
                    dependency_versions[group_id] = version  # Also add group for broader matching
                    logger.debug(f"Found Gradle dependency: {package_name} -> {version}")

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


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Java code structure and embeddings loader")
    add_common_args(parser)
    parser.add_argument("repo_url", help="Git repository URL or local path to analyze")
    parser.add_argument("--batch-size", type=int, help="Override automatic batch size selection")
    parser.add_argument(
        "--parallel-files",
        type=int,
        default=4,
        help="Number of files to process in parallel",
    )
    return parser.parse_args()


def get_device():
    """Get the appropriate device for PyTorch computations."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    else:
        return torch.device("cpu")


def get_optimal_batch_size(device):
    """Determine optimal batch size based on device and available memory."""
    if device.type == "cuda":
        gpu_memory = torch.cuda.get_device_properties(0).total_memory
        if gpu_memory > 20 * 1024**3:  # >20GB (RTX 4090, etc.)
            return 512  # Push even harder
        elif gpu_memory > 10 * 1024**3:  # >10GB
            return 256
        else:  # 8GB or less
            return 128
    elif device.type == "mps":
        # Apple Silicon unified memory can handle large batches
        return 256
    else:
        return 32


def compute_embeddings_bulk(snippets, tokenizer, model, device, batch_size):
    """Compute embeddings for all snippets using maximum batching."""
    if not snippets:
        return []

    logger.info(f"Computing {len(snippets)} embeddings with batch size {batch_size}")

    all_embeddings = []
    use_amp = device.type == "cuda" and hasattr(torch.cuda, "amp")

    # Process in batches
    for i in tqdm(range(0, len(snippets), batch_size), desc="Computing embeddings"):
        batch_snippets = snippets[i : i + batch_size]

        # Tokenize batch
        tokens = tokenizer(
            batch_snippets,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        # Move to device efficiently
        tokens = {k: v.to(device, non_blocking=True) for k, v in tokens.items()}

        # Compute embeddings
        with torch.no_grad():
            if use_amp:
                with torch.amp.autocast("cuda"):
                    outputs = model(**tokens)
            else:
                outputs = model(**tokens)

            # Use [CLS] token embedding (first token)
            embeddings = outputs.last_hidden_state[:, 0, :].cpu().numpy()

        # Convert to lists and store
        batch_embeddings = [embedding.tolist() for embedding in embeddings]
        all_embeddings.extend(batch_embeddings)

        # Cleanup
        del tokens, outputs, embeddings
        if i % (batch_size * 4) == 0:  # Periodic cleanup
            gc.collect()
            if device.type == "cuda":
                torch.cuda.empty_cache()
            elif device.type == "mps":
                torch.mps.empty_cache()

    logger.info(f"Computed {len(all_embeddings)} embeddings")
    return all_embeddings


def extract_file_data(file_path, repo_root):
    """Extract all data from a single Java file including classes, interfaces, and inheritance."""
    rel_path = str(file_path.relative_to(repo_root))

    try:
        # Read file
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception as e:
        logger.error("Error reading file %s: %s", file_path, e)
        return None

    # Parse Java and extract imports, classes, interfaces, and methods
    methods = []
    classes = []
    interfaces = []
    imports = []

    try:
        tree = javalang.parse.parse(code)

        # Extract import declarations
        if hasattr(tree, "imports") and tree.imports:
            for import_stmt in tree.imports:
                try:
                    import_path = import_stmt.path
                    is_static = import_stmt.static if hasattr(import_stmt, "static") else False
                    is_wildcard = (
                        import_stmt.wildcard if hasattr(import_stmt, "wildcard") else False
                    )

                    # Classify import type
                    import_type = "external"
                    if import_path.startswith("java.") or import_path.startswith("javax."):
                        import_type = "standard"
                    elif import_path.startswith("org.neo4j"):
                        import_type = "internal"

                    import_info = {
                        "import_path": import_path,
                        "is_static": is_static,
                        "is_wildcard": is_wildcard,
                        "import_type": import_type,
                        "file": rel_path,
                    }
                    imports.append(import_info)

                except Exception as e:
                    logger.debug("Error processing import in %s: %s", rel_path, e)
                    continue

        # Extract class declarations
        for path_to_node, node in tree.filter(javalang.tree.ClassDeclaration):
            try:
                class_info = {
                    "name": node.name,
                    "type": "class",
                    "file": rel_path,
                    "line": node.position.line if node.position else None,
                    "modifiers": [mod for mod in (node.modifiers or [])],
                    "extends": node.extends.name if node.extends else None,
                    "implements": [impl.name for impl in (node.implements or [])],
                    "is_abstract": "abstract" in (node.modifiers or []),
                    "is_final": "final" in (node.modifiers or []),
                }

                # Calculate class metrics
                class_lines = code.splitlines()
                if node.position and node.position.line:
                    start_line = node.position.line - 1
                    # Find class end (simplified)
                    brace_count = 0
                    end_line = start_line
                    for i, line in enumerate(class_lines[start_line:], start_line):
                        if "{" in line:
                            brace_count += line.count("{")
                        if "}" in line:
                            brace_count -= line.count("}")
                            if brace_count <= 0:
                                end_line = i + 1
                                break
                        if i - start_line > 1000:  # Safety limit
                            end_line = i + 1
                            break

                    class_info["estimated_lines"] = end_line - start_line

                classes.append(class_info)

            except Exception as e:
                logger.debug("Error processing class %s in %s: %s", node.name, rel_path, e)
                continue

        # Extract interface declarations
        for path_to_node, node in tree.filter(javalang.tree.InterfaceDeclaration):
            try:
                interface_info = {
                    "name": node.name,
                    "type": "interface",
                    "file": rel_path,
                    "line": node.position.line if node.position else None,
                    "modifiers": [mod for mod in (node.modifiers or [])],
                    "extends": [
                        ext.name for ext in (node.extends or [])
                    ],  # Interfaces can extend multiple
                    "method_count": 0,  # Will be calculated later
                }
                interfaces.append(interface_info)

            except Exception as e:
                logger.debug("Error processing interface %s in %s: %s", node.name, rel_path, e)
                continue

        # Extract method declarations
        for path_to_node, node in tree.filter(javalang.tree.MethodDeclaration):
            try:
                start_line = node.position.line if node.position else None
                method_name = node.name

                # Find containing class/interface with full qualified name
                containing_class = None
                containing_type = None
                for ancestor in reversed(path_to_node):
                    if isinstance(ancestor, javalang.tree.ClassDeclaration):
                        containing_class = ancestor.name
                        containing_type = "class"
                        break
                    elif isinstance(ancestor, javalang.tree.InterfaceDeclaration):
                        containing_class = ancestor.name
                        containing_type = "interface"
                        break

                # Extract method code and calculate metrics
                method_code = ""
                estimated_lines = 0
                if start_line:
                    code_lines = code.splitlines()
                    end_line = start_line
                    brace_count = 0

                    # Find method end by counting braces
                    for i, line in enumerate(code_lines[start_line - 1 :], start_line - 1):
                        if "{" in line:
                            brace_count += line.count("{")
                        if "}" in line:
                            brace_count -= line.count("}")
                            if brace_count <= 0:
                                end_line = i + 1
                                break
                        if i - start_line > 200:  # Safety limit
                            end_line = i + 1
                            break

                    method_code = "\n".join(code_lines[start_line - 1 : end_line])
                    estimated_lines = end_line - start_line + 1

                # Extract method calls within this method
                method_calls = _extract_method_calls(method_code, containing_class)

                method_info = {
                    "name": method_name,
                    "class": containing_class,
                    "containing_type": containing_type,
                    "line": start_line,
                    "code": method_code,
                    "file": rel_path,
                    "estimated_lines": estimated_lines,
                    "modifiers": [mod for mod in (node.modifiers or [])],
                    "is_static": "static" in (node.modifiers or []),
                    "is_abstract": "abstract" in (node.modifiers or []),
                    "is_final": "final" in (node.modifiers or []),
                    "is_private": "private" in (node.modifiers or []),
                    "is_public": "public" in (node.modifiers or []),
                    "return_type": (str(node.return_type) if node.return_type else "void"),
                    "calls": method_calls,  # List of method calls made by this method
                }
                methods.append(method_info)

            except Exception as e:
                logger.debug("Error processing method %s in %s: %s", node.name, rel_path, e)
                continue

        # Update interface method counts
        for interface in interfaces:
            interface["method_count"] = sum(1 for m in methods if m["class"] == interface["name"])

    except Exception as e:
        logger.warning("Failed to parse Java file %s: %s", rel_path, e)

    # Calculate file-level metrics
    file_lines = len(code.splitlines())
    code_lines = len(
        [line for line in code.splitlines() if line.strip() and not line.strip().startswith("//")]
    )

    return {
        "path": rel_path,
        "code": code,
        "methods": methods,
        "classes": classes,
        "interfaces": interfaces,
        "imports": imports,
        "language": "java",  # Set language for CVE analysis
        "ecosystem": "maven",  # Java ecosystem
        "total_lines": file_lines,
        "code_lines": code_lines,
        "method_count": len(methods),
        "class_count": len(classes),
        "interface_count": len(interfaces),
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
            skip_keywords = {
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

            if method_name.lower() in skip_keywords:
                continue

            # Skip obvious constructors (capitalized method names)
            if method_name[0].isupper():
                continue

            # Determine target class/object
            target_class = None
            call_type = "unknown"

            if qualifier is None:
                # Direct method call - assume same class
                target_class = containing_class
                call_type = "same_class"
            elif qualifier == "this":
                target_class = containing_class
                call_type = "this"
            elif qualifier == "super":
                target_class = "super"  # We'll resolve inheritance later
                call_type = "super"
            elif qualifier[0].isupper():
                # Capitalized qualifier likely a class name (static call)
                target_class = qualifier
                call_type = "static"
            else:
                # Lowercase qualifier likely an object instance
                target_class = qualifier  # We'll resolve the type later if possible
                call_type = "instance"

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


def bulk_create_nodes_and_relationships(
    session, files_data, file_embeddings, method_embeddings, dependency_versions=None
):
    """Create all nodes and relationships using bulk operations."""
    logger.info("Creating directory structure...")

    # 1. Create all directories first
    directories = set()
    for file_data in files_data:
        path_parts = Path(file_data["path"]).parent.parts
        for i in range(len(path_parts) + 1):
            dir_path = str(Path(*path_parts[:i])) if i > 0 else ""
            directories.add(dir_path)

    # Bulk create directories
    session.run(
        "UNWIND $directories AS dir_path " "MERGE (:Directory {path: dir_path})",
        directories=list(directories),
    )

    # 2. Create directory relationships
    dir_relationships = []
    for directory in directories:
        if directory:  # Not root
            parent = str(Path(directory).parent) if Path(directory).parent != Path(".") else ""
            dir_relationships.append({"parent": parent, "child": directory})

    if dir_relationships:
        session.run(
            "UNWIND $rels AS rel "
            "MATCH (parent:Directory {path: rel.parent}) "
            "MATCH (child:Directory {path: rel.child}) "
            "MERGE (parent)-[:CONTAINS]->(child)",
            rels=dir_relationships,
        )

    logger.info("Creating file nodes...")

    # 3. Bulk create file nodes with metrics
    file_nodes = []
    for i, file_data in enumerate(files_data):
        file_node = {
            "path": file_data["path"],
            "embedding": file_embeddings[i],
            "embedding_type": EMBEDDING_TYPE,
            "language": file_data.get("language", "java"),
            "ecosystem": file_data.get("ecosystem", "maven"),
            "total_lines": file_data.get("total_lines", 0),
            "code_lines": file_data.get("code_lines", 0),
            "method_count": file_data.get("method_count", 0),
            "class_count": file_data.get("class_count", 0),
            "interface_count": file_data.get("interface_count", 0),
        }
        file_nodes.append(file_node)

    session.run(
        "UNWIND $files AS file "
        "MERGE (f:File {path: file.path}) "
        "SET f.embedding = file.embedding, f.embedding_type = file.embedding_type, "
        "f.language = file.language, f.ecosystem = file.ecosystem, "
        "f.total_lines = file.total_lines, f.code_lines = file.code_lines, "
        "f.method_count = file.method_count, f.class_count = file.class_count, "
        "f.interface_count = file.interface_count",
        files=file_nodes,
    )

    # 4. Create file-to-directory relationships
    file_dir_rels = []
    for file_data in files_data:
        parent_dir = (
            str(Path(file_data["path"]).parent)
            if Path(file_data["path"]).parent != Path(".")
            else ""
        )
        file_dir_rels.append({"file": file_data["path"], "directory": parent_dir})

    session.run(
        "UNWIND $rels AS rel "
        "MATCH (d:Directory {path: rel.directory}) "
        "MATCH (f:File {path: rel.file}) "
        "MERGE (d)-[:CONTAINS]->(f)",
        rels=file_dir_rels,
    )

    # 5. Create Class and Interface nodes with inheritance relationships
    logger.info("Creating class and interface nodes...")

    # Collect all classes and interfaces
    all_classes = []
    all_interfaces = []
    class_inheritance = []
    interface_inheritance = []
    class_implementations = []

    for file_data in files_data:
        # Process classes
        for class_info in file_data.get("classes", []):
            class_node = {
                "name": class_info["name"],
                "file": class_info["file"],
                "line": class_info.get("line"),
                "estimated_lines": class_info.get("estimated_lines", 0),
                "is_abstract": class_info.get("is_abstract", False),
                "is_final": class_info.get("is_final", False),
                "modifiers": class_info.get("modifiers", []),
            }
            all_classes.append(class_node)

            # Track inheritance relationships
            if class_info.get("extends"):
                class_inheritance.append(
                    {
                        "child": class_info["name"],
                        "child_file": class_info["file"],
                        "parent": class_info["extends"],
                    }
                )

            # Track interface implementations
            for interface in class_info.get("implements", []):
                class_implementations.append(
                    {
                        "class": class_info["name"],
                        "class_file": class_info["file"],
                        "interface": interface,
                    }
                )

        # Process interfaces
        for interface_info in file_data.get("interfaces", []):
            interface_node = {
                "name": interface_info["name"],
                "file": interface_info["file"],
                "line": interface_info.get("line"),
                "method_count": interface_info.get("method_count", 0),
                "modifiers": interface_info.get("modifiers", []),
            }
            all_interfaces.append(interface_node)

            # Track interface inheritance (extends)
            for extended_interface in interface_info.get("extends", []):
                interface_inheritance.append(
                    {
                        "child": interface_info["name"],
                        "child_file": interface_info["file"],
                        "parent": extended_interface,
                    }
                )

    # Bulk create class nodes
    if all_classes:
        logger.info(f"Creating {len(all_classes)} class nodes...")
        session.run(
            "UNWIND $classes AS class "
            "MERGE (c:Class {name: class.name, file: class.file}) "
            "SET c.line = class.line, c.estimated_lines = class.estimated_lines, "
            "c.is_abstract = class.is_abstract, c.is_final = class.is_final, "
            "c.modifiers = class.modifiers",
            classes=all_classes,
        )

    # Bulk create interface nodes
    if all_interfaces:
        logger.info(f"Creating {len(all_interfaces)} interface nodes...")
        session.run(
            "UNWIND $interfaces AS interface "
            "MERGE (i:Interface {name: interface.name, file: interface.file}) "
            "SET i.line = interface.line, i.method_count = interface.method_count, "
            "i.modifiers = interface.modifiers",
            interfaces=all_interfaces,
        )

    # Create class inheritance relationships (EXTENDS)
    if class_inheritance:
        logger.info(f"Creating {len(class_inheritance)} class inheritance relationships...")
        session.run(
            "UNWIND $inheritance AS rel "
            "MATCH (child:Class {name: rel.child, file: rel.child_file}) "
            "MERGE (parent:Class {name: rel.parent}) "
            "MERGE (child)-[:EXTENDS]->(parent)",
            inheritance=class_inheritance,
        )

    # Create interface inheritance relationships (EXTENDS)
    if interface_inheritance:
        logger.info(f"Creating {len(interface_inheritance)} interface inheritance relationships...")
        session.run(
            "UNWIND $inheritance AS rel "
            "MATCH (child:Interface {name: rel.child, file: rel.child_file}) "
            "MERGE (parent:Interface {name: rel.parent}) "
            "MERGE (child)-[:EXTENDS]->(parent)",
            inheritance=interface_inheritance,
        )

    # Create class-interface implementation relationships (IMPLEMENTS)
    if class_implementations:
        logger.info(f"Creating {len(class_implementations)} implementation relationships...")
        session.run(
            "UNWIND $implementations AS rel "
            "MATCH (c:Class {name: rel.class, file: rel.class_file}) "
            "MERGE (i:Interface {name: rel.interface}) "
            "MERGE (c)-[:IMPLEMENTS]->(i)",
            implementations=class_implementations,
        )

    # Create file-to-class relationships
    file_class_rels = []
    for file_data in files_data:
        for class_info in file_data.get("classes", []):
            file_class_rels.append({"file": file_data["path"], "class": class_info["name"]})

    if file_class_rels:
        session.run(
            "UNWIND $rels AS rel "
            "MATCH (f:File {path: rel.file}) "
            "MATCH (c:Class {name: rel.class, file: rel.file}) "
            "MERGE (f)-[:DEFINES]->(c)",
            rels=file_class_rels,
        )

    # Create file-to-interface relationships
    file_interface_rels = []
    for file_data in files_data:
        for interface_info in file_data.get("interfaces", []):
            file_interface_rels.append(
                {"file": file_data["path"], "interface": interface_info["name"]}
            )

    if file_interface_rels:
        session.run(
            "UNWIND $rels AS rel "
            "MATCH (f:File {path: rel.file}) "
            "MATCH (i:Interface {name: rel.interface, file: rel.file}) "
            "MERGE (f)-[:DEFINES]->(i)",
            rels=file_interface_rels,
        )

    logger.info("Creating method nodes...")

    # 6. Bulk create method nodes with metrics
    method_nodes = []
    method_idx = 0

    for file_data in files_data:
        for method in file_data["methods"]:
            method_node = {
                "name": method["name"],
                "file": method["file"],
                "line": method["line"],
                "embedding": method_embeddings[method_idx],
                "embedding_type": EMBEDDING_TYPE,
                "estimated_lines": method.get("estimated_lines", 0),
                "is_static": method.get("is_static", False),
                "is_abstract": method.get("is_abstract", False),
                "is_final": method.get("is_final", False),
                "is_private": method.get("is_private", False),
                "is_public": method.get("is_public", False),
                "return_type": method.get("return_type", "void"),
                "modifiers": method.get("modifiers", []),
            }
            if method["class"]:
                method_node["class"] = method["class"]
                method_node["containing_type"] = method.get("containing_type", "class")

            method_nodes.append(method_node)
            method_idx += 1

    # Split method creation into batches to avoid huge queries
    batch_size = 1000
    total_batches = (len(method_nodes) + batch_size - 1) // batch_size
    logger.info(f"Creating {len(method_nodes)} method nodes in {total_batches} batches...")

    for i in range(0, len(method_nodes), batch_size):
        batch_num = i // batch_size + 1
        batch = method_nodes[i : i + batch_size]

        logger.info(f"Creating method batch {batch_num}/{total_batches} ({len(batch)} methods)...")
        start_time = perf_counter()

        session.run(
            "UNWIND $methods AS method "
            "MERGE (m:Method {name: method.name, file: method.file, line: method.line}) "
            "SET m.embedding = method.embedding, m.embedding_type = method.embedding_type, "
            "m.estimated_lines = method.estimated_lines, m.is_static = method.is_static, "
            "m.is_abstract = method.is_abstract, m.is_final = method.is_final, "
            "m.is_private = method.is_private, m.is_public = method.is_public, "
            "m.return_type = method.return_type, m.modifiers = method.modifiers "
            + (
                "SET m.class = method.class, m.containing_type = method.containing_type "
                if any("class" in m for m in batch)
                else ""
            ),
            methods=batch,
        )

        batch_time = perf_counter() - start_time
        logger.info(f"Batch {batch_num} completed in {batch_time:.1f}s")

    # 6. Create method-to-file relationships
    method_file_rels = []
    for file_data in files_data:
        for method in file_data["methods"]:
            method_file_rels.append(
                {
                    "method_name": method["name"],
                    "method_line": method["line"],
                    "file_path": method["file"],
                }
            )

    # Batch the relationships too
    total_rel_batches = (len(method_file_rels) + batch_size - 1) // batch_size
    logger.info(
        f"Creating {len(method_file_rels)} method-file relationships in {total_rel_batches} batches..."
    )

    for i in range(0, len(method_file_rels), batch_size):
        batch_num = i // batch_size + 1
        batch = method_file_rels[i : i + batch_size]

        logger.info(
            f"Creating relationship batch {batch_num}/{total_rel_batches} ({len(batch)} relationships)..."
        )
        start_time = perf_counter()

        session.run(
            "UNWIND $rels AS rel "
            "MATCH (f:File {path: rel.file_path}) "
            "MATCH (m:Method {name: rel.method_name, file: rel.file_path, line: rel.method_line}) "
            "MERGE (f)-[:DECLARES]->(m)",
            rels=batch,
        )

        batch_time = perf_counter() - start_time
        logger.info(f"Relationship batch {batch_num} completed in {batch_time:.1f}s")

    # 7. Create method-to-class/interface relationships
    method_class_rels = []
    method_interface_rels = []

    for file_data in files_data:
        for method in file_data["methods"]:
            if method.get("class"):
                if method.get("containing_type") == "interface":
                    method_interface_rels.append(
                        {
                            "method_name": method["name"],
                            "method_file": method["file"],
                            "method_line": method["line"],
                            "interface_name": method["class"],
                        }
                    )
                else:  # class or default
                    method_class_rels.append(
                        {
                            "method_name": method["name"],
                            "method_file": method["file"],
                            "method_line": method["line"],
                            "class_name": method["class"],
                        }
                    )

    # Create method-to-class relationships
    if method_class_rels:
        logger.info(f"Creating {len(method_class_rels)} method-to-class relationships...")
        for i in range(0, len(method_class_rels), batch_size):
            batch = method_class_rels[i : i + batch_size]
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (m:Method {name: rel.method_name, file: rel.method_file, line: rel.method_line}) "
                "MATCH (c:Class {name: rel.class_name, file: rel.method_file}) "
                "MERGE (c)-[:CONTAINS_METHOD]->(m)",
                rels=batch,
            )

    # Create method-to-interface relationships
    if method_interface_rels:
        logger.info(f"Creating {len(method_interface_rels)} method-to-interface relationships...")
        for i in range(0, len(method_interface_rels), batch_size):
            batch = method_interface_rels[i : i + batch_size]
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (m:Method {name: rel.method_name, file: rel.method_file, line: rel.method_line}) "
                "MATCH (i:Interface {name: rel.interface_name, file: rel.method_file}) "
                "MERGE (i)-[:CONTAINS_METHOD]->(m)",
                rels=batch,
            )

    # 8. Create method call relationships (CALLS)
    # 9. Create Import nodes and IMPORTS relationships
    logger.info("Creating import nodes and relationships...")

    # Collect all imports and create external dependencies
    all_imports = []
    external_dependencies = set()

    for file_data in files_data:
        for import_info in file_data.get("imports", []):
            all_imports.append(import_info)

            # Create external dependency entries for external imports
            if import_info["import_type"] == "external":
                # Extract base package for dependency grouping
                import_path = import_info["import_path"]
                if "." in import_path:
                    # Group by organization (e.g., com.fasterxml.jackson.* -> com.fasterxml.jackson)
                    parts = import_path.split(".")
                    if len(parts) >= 3:
                        base_package = ".".join(parts[:3])  # e.g., com.fasterxml.jackson
                        external_dependencies.add(base_package)

    # Bulk create Import nodes
    if all_imports:
        logger.info(f"Creating {len(all_imports)} import nodes...")

        # Use the same batching approach as methods for consistency and performance
        batch_size = 1000
        total_batches = (len(all_imports) + batch_size - 1) // batch_size
        logger.info(f"Creating {len(all_imports)} import nodes in {total_batches} batches...")

        for i in range(0, len(all_imports), batch_size):
            batch_num = i // batch_size + 1
            batch = all_imports[i : i + batch_size]

            logger.info(
                f"Creating import batch {batch_num}/{total_batches} ({len(batch)} imports)..."
            )
            start_time = perf_counter()

            session.run(
                "UNWIND $imports AS imp "
                "MERGE (i:Import {import_path: imp.import_path}) "
                "SET i.is_static = imp.is_static, i.is_wildcard = imp.is_wildcard, "
                "i.import_type = imp.import_type",
                imports=batch,
            )

            batch_time = perf_counter() - start_time
            logger.info(f"Import batch {batch_num} completed in {batch_time:.1f}s")

        # Create IMPORTS relationships using batching
        logger.info(
            f"Creating {len(all_imports)} IMPORTS relationships in {total_batches} batches..."
        )

        for i in range(0, len(all_imports), batch_size):
            batch_num = i // batch_size + 1
            batch = all_imports[i : i + batch_size]

            logger.info(
                f"Creating IMPORTS relationship batch {batch_num}/{total_batches} ({len(batch)} relationships)..."
            )
            start_time = perf_counter()

            session.run(
                "UNWIND $imports AS imp "
                "MATCH (f:File {path: imp.file}) "
                "MATCH (i:Import {import_path: imp.import_path}) "
                "MERGE (f)-[:IMPORTS]->(i)",
                imports=batch,
            )

            batch_time = perf_counter() - start_time
            logger.info(f"IMPORTS relationship batch {batch_num} completed in {batch_time:.1f}s")

    # Create ExternalDependency nodes for CVE analysis
    if external_dependencies:
        logger.info(f"Creating {len(external_dependencies)} external dependency nodes...")
        dependency_nodes = []

        for dep in external_dependencies:
            # Try to find version information
            version = None
            if dependency_versions:
                # Try exact match first
                if dep in dependency_versions:
                    version = dependency_versions[dep]
                else:
                    # Try partial matches (e.g., for com.fasterxml.jackson.core match
                    # com.fasterxml.jackson)
                    for dep_key, dep_version in dependency_versions.items():
                        if dep.startswith(dep_key) or dep_key.startswith(dep):
                            version = dep_version
                            break

            dependency_node = {"package": dep, "language": "java", "ecosystem": "maven"}

            # Add version if found
            if version:
                dependency_node["version"] = version
                logger.debug(f"📦 {dep} -> version {version}")
            else:
                logger.debug(f"📦 {dep} -> no version found")

            dependency_nodes.append(dependency_node)

        # Create nodes with version information
        if dependency_versions:
            session.run(
                "UNWIND $dependencies AS dep "
                "MERGE (e:ExternalDependency {package: dep.package}) "
                "SET e.language = dep.language, e.ecosystem = dep.ecosystem, "
                "e.version = CASE WHEN dep.version IS NOT NULL THEN dep.version ELSE e.version END",
                dependencies=dependency_nodes,
            )
        else:
            session.run(
                "UNWIND $dependencies AS dep "
                "MERGE (e:ExternalDependency {package: dep.package}) "
                "SET e.language = dep.language, e.ecosystem = dep.ecosystem",
                dependencies=dependency_nodes,
            )

        # Create relationships from Import nodes to ExternalDependency nodes
        session.run(
            "MATCH (i:Import) "
            "WHERE i.import_type = 'external' "
            "WITH i, SPLIT(i.import_path, '.') AS parts "
            "WHERE SIZE(parts) >= 3 "
            "WITH i, parts[0] + '.' + parts[1] + '.' + parts[2] AS base_package "
            "MATCH (e:ExternalDependency {package: base_package}) "
            "MERGE (i)-[:DEPENDS_ON]->(e)"
        )

    # 10. Create method call relationships
    logger.info("Creating method call relationships...")
    method_call_rels = []

    for file_data in files_data:
        for method in file_data["methods"]:
            for call in method.get("calls", []):
                # Create relationship for each method call
                method_call_rels.append(
                    {
                        "caller_name": method["name"],
                        "caller_file": method["file"],
                        "caller_line": method["line"],
                        "caller_class": method.get("class"),
                        "callee_name": call["method_name"],
                        "callee_class": call["target_class"],
                        "call_type": call["call_type"],
                        "qualifier": call.get("qualifier"),
                    }
                )

    if method_call_rels:
        logger.info(f"Processing {len(method_call_rels)} method call relationships...")

        # Group by call type for different handling
        same_class_calls = [r for r in method_call_rels if r["call_type"] in ["same_class", "this"]]
        static_calls = [r for r in method_call_rels if r["call_type"] == "static"]
        other_calls = [
            r for r in method_call_rels if r["call_type"] not in ["same_class", "this", "static"]
        ]

        # Handle same-class calls (most reliable)
        if same_class_calls:
            logger.info(f"Creating {len(same_class_calls)} same-class method calls...")
            for i in range(0, len(same_class_calls), batch_size):
                batch = same_class_calls[i : i + batch_size]
                session.run(
                    "UNWIND $calls AS call "
                    "MATCH (caller:Method {name: call.caller_name, "
                    "file: call.caller_file, line: call.caller_line}) "
                    "MATCH (callee:Method {name: call.callee_name, class: call.callee_class}) "
                    "WHERE caller.file = callee.file "  # Same file for same-class calls
                    "MERGE (caller)-[:CALLS {type: call.call_type}]->(callee)",
                    calls=batch,
                )

        # Handle static calls (by class name)
        if static_calls:
            logger.info(f"Creating {len(static_calls)} static method calls...")
            for i in range(0, len(static_calls), batch_size):
                batch = static_calls[i : i + batch_size]
                session.run(
                    "UNWIND $calls AS call "
                    "MATCH (caller:Method {name: call.caller_name, "
                    "file: call.caller_file, line: call.caller_line}) "
                    "MATCH (callee:Method {name: call.callee_name, class: call.callee_class}) "
                    "WHERE callee.is_static = true "
                    "MERGE (caller)-[:CALLS {type: call.call_type, "
                    "qualifier: call.qualifier}]->(callee)",
                    calls=batch,
                )

        # Handle other calls (best effort - by method name only)
        if other_calls:
            logger.info(f"Creating {len(other_calls)} other method calls (best effort)...")

            # Use much smaller batches for this problematic section
            small_batch_size = 100  # Much smaller than normal batch_size
            total_small_batches = (len(other_calls) + small_batch_size - 1) // small_batch_size

            logger.warning(
                f"⚠️ Using small batches ({small_batch_size}) for complex method matching"
            )

            successful_calls = 0
            failed_batches = 0

            for i in range(0, len(other_calls), small_batch_size):
                batch_num = i // small_batch_size + 1
                batch = other_calls[i : i + small_batch_size]

                try:
                    logger.info(
                        f"Processing small batch {batch_num}/{total_small_batches} ({len(batch)} calls)..."
                    )
                    start_time = perf_counter()

                    # Use a more conservative query with timeouts
                    result = session.run(
                        "UNWIND $calls AS call "
                        "MATCH (caller:Method {name: call.caller_name, "
                        "file: call.caller_file, line: call.caller_line}) "
                        "OPTIONAL MATCH (callee:Method {name: call.callee_name}) "
                        "WHERE callee IS NOT NULL "
                        "WITH caller, callee, call LIMIT 500 "  # Limit matches per batch
                        "MERGE (caller)-[:CALLS {type: call.call_type, "
                        "qualifier: call.qualifier}]->(callee) "
                        "RETURN count(*) as created",
                        calls=batch,
                    )

                    created = result.single()["created"]
                    successful_calls += created

                    batch_time = perf_counter() - start_time
                    logger.info(
                        f"Small batch {batch_num} completed: {created} relationships in {batch_time:.1f}s"
                    )

                    # Add a longer pause between batches to let database recover
                    if batch_num < total_small_batches:
                        time.sleep(0.5)

                except Exception as e:
                    failed_batches += 1
                    logger.warning(f"Batch {batch_num} failed (continuing): {e}")

                    # If too many failures, stop to avoid further database issues
                    if failed_batches > 10:
                        logger.error(
                            "Too many failed batches, stopping other method calls processing"
                        )
                        break

            logger.info(
                f"Other method calls completed: {successful_calls} relationships created, "
                f"{failed_batches} batches failed"
            )

    logger.info("Bulk creation completed!")


def main():
    """Main function."""
    args = parse_args()

    setup_logging(args.log_level, args.log_file)
    driver = create_neo4j_driver(args.uri, args.username, args.password)

    try:
        with driver.session(database=args.database) as session:
            # Check if repo_url is a local path or a URL
            repo_path = Path(args.repo_url)
            if repo_path.exists() and repo_path.is_dir():
                # Local path - use directly
                logger.info("Using local repository: %s", args.repo_url)
                repo_root = repo_path
                tmpdir = None

                java_files = list(repo_root.rglob("*.java"))
                logger.info("Found %d Java files to process", len(java_files))
            else:
                # URL - clone to temporary directory
                tmpdir = tempfile.mkdtemp()
                logger.info("Cloning %s...", args.repo_url)
                import git

                git.Repo.clone_from(args.repo_url, tmpdir)

                repo_root = Path(tmpdir)
                java_files = list(repo_root.rglob("*.java"))
                logger.info("Found %d Java files to process", len(java_files))

            # Extract dependency versions from build files
            dependency_versions = extract_dependency_versions_from_files(repo_root)

            # Phase 1: Extract all file data in parallel
            logger.info("Phase 1: Extracting file data...")
            start_phase1 = perf_counter()

            files_data = []
            with ThreadPoolExecutor(max_workers=args.parallel_files) as executor:
                future_to_file = {
                    executor.submit(extract_file_data, file_path, repo_root): file_path
                    for file_path in java_files
                }

                for future in tqdm(
                    as_completed(future_to_file),
                    total=len(java_files),
                    desc="Extracting files",
                ):
                    result = future.result()
                    if result:
                        files_data.append(result)

            phase1_time = perf_counter() - start_phase1
            logger.info("Phase 1 completed in %.2fs", phase1_time)

            # Phase 2: Compute all embeddings in bulk
            logger.info("Phase 2: Computing embeddings...")
            start_phase2 = perf_counter()

            # Initialize model
            logger.info("Loading GraphCodeBERT model...")
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

            # Compute embeddings with batching
            batch_size = args.batch_size if args.batch_size else get_optimal_batch_size(device)
            logger.info(f"Using batch size: {batch_size}")

            # Collect all code snippets
            file_snippets = [file_data["code"] for file_data in files_data]
            method_snippets = []
            for file_data in files_data:
                for method in file_data["methods"]:
                    method_snippets.append(method["code"])

            logger.info(
                "Computing embeddings for %d files and %d methods",
                len(file_snippets),
                len(method_snippets),
            )

            # Compute embeddings
            file_embeddings = compute_embeddings_bulk(
                file_snippets, tokenizer, model, device, batch_size
            )
            method_embeddings = compute_embeddings_bulk(
                method_snippets, tokenizer, model, device, batch_size
            )

            phase2_time = perf_counter() - start_phase2
            logger.info("Phase 2 completed in %.2fs", phase2_time)

            # Phase 3: Bulk create everything in Neo4j
            logger.info("Phase 3: Creating graph in Neo4j...")
            start_phase3 = perf_counter()

            bulk_create_nodes_and_relationships(
                session,
                files_data,
                file_embeddings,
                method_embeddings,
                dependency_versions,
            )

            phase3_time = perf_counter() - start_phase3
            logger.info("Phase 3 completed in %.2fs", phase3_time)

            total_time = phase1_time + phase2_time + phase3_time
            logger.info(
                "TOTAL: Processed %d files in %.2fs (%.2f files/sec)",
                len(files_data),
                total_time,
                len(files_data) / total_time,
            )
            logger.info(
                "Phase breakdown: Extract=%.1fs, Embeddings=%.1fs, Database=%.1fs",
                phase1_time,
                phase2_time,
                phase3_time,
            )

            # Clean up temporary directory if we created one
            if tmpdir:
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)
                logger.info("Cleaned up temporary repository clone")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
