#!/usr/bin/env python3

from __future__ import annotations

import logging
from typing import Any

from tqdm import tqdm

from ..analysis.types import FileData
from ..constants import (
    DB_BATCH_SIMPLE,
    DB_BATCH_WITH_EMBEDDINGS,
    EMBEDDING_TYPE,
)

logger = logging.getLogger(__name__)


def _get_database_batch_size(
    has_embeddings: bool = False, estimated_size_mb: int | None = None
) -> int:
    if has_embeddings:
        return DB_BATCH_WITH_EMBEDDINGS
    elif estimated_size_mb and estimated_size_mb > 1:
        return 500
    else:
        return DB_BATCH_SIMPLE


def create_directories(session: Any, files_data: list[FileData]) -> None:
    batch_size = 1000

    directories = set()
    for file_data in files_data:
        from pathlib import Path

        path_parts = Path(file_data["path"]).parent.parts
        for i in range(len(path_parts) + 1):
            dir_path = str(Path(*path_parts[:i])) if i > 0 else ""
            directories.add(dir_path)

    directories_list = list(directories)
    if directories_list:
        logger.info(f"Creating {len(directories_list)} directory nodes...")
        for i in range(0, len(directories_list), batch_size):
            batch_num = i // batch_size + 1
            batch = directories_list[i : i + batch_size]
            logger.debug(f"Creating directory batch {batch_num} ({len(batch)} directories)")
            session.run(
                "UNWIND $directories AS dir_path MERGE (:Directory {path: dir_path})",
                directories=batch,
            )

    dir_relationships = []
    from pathlib import Path as _P

    for directory in directories:
        if directory:
            parent = str(_P(directory).parent) if _P(directory).parent != _P(".") else ""
            dir_relationships.append({"parent": parent, "child": directory})

    if dir_relationships:
        logger.info(f"Creating {len(dir_relationships)} directory relationships...")
        for i in range(0, len(dir_relationships), batch_size):
            batch_num = i // batch_size + 1
            batch = dir_relationships[i : i + batch_size]
            logger.debug(
                f"Creating directory relationship batch {batch_num} ({len(batch)} relationships)"
            )
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (parent:Directory {path: rel.parent}) "
                "MATCH (child:Directory {path: rel.child}) "
                "MERGE (parent)-[:CONTAINS]->(child)",
                rels=batch,
            )


def create_files(
    session: Any, files_data: list[FileData], file_embeddings: list[list[float]]
) -> None:
    batch_size = _get_database_batch_size(has_embeddings=True)

    file_nodes: list[dict[str, Any]] = []
    warned_short = False
    import numpy as _np

    for i, file_data in enumerate(files_data):
        from pathlib import Path as _Path

        file_path_str = file_data["path"]
        file_name_only = _Path(file_path_str).name if file_path_str else file_path_str
        has_embedding = i < len(file_embeddings)
        if not has_embedding and not warned_short:
            logger.warning(
                "Missing file embedding(s) (%d embeddings for %d files); leaving embedding unset",
                len(file_embeddings),
                len(files_data),
            )
            warned_short = True
        emb_value = None
        if has_embedding:
            try:
                emb = file_embeddings[i]
                emb_value = emb.tolist() if isinstance(emb, _np.ndarray) else emb  # type: ignore[arg-type]
            except Exception:
                emb_value = None

        try:
            from constants import EMBEDDING_PROPERTY as _EMB_PROP
        except Exception:  # pragma: no cover
            from src.constants import EMBEDDING_PROPERTY as _EMB_PROP  # type: ignore
        file_node = {
            "path": file_path_str,
            "name": file_name_only,
            **({_EMB_PROP: emb_value} if has_embedding and emb_value is not None else {}),
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

    if file_nodes:
        logger.info(f"Creating {len(file_nodes)} file nodes...")
        for i in range(0, len(file_nodes), batch_size):
            batch_num = i // batch_size + 1
            batch = file_nodes[i : i + batch_size]
            logger.debug(f"Creating file batch {batch_num} ({len(batch)} files)")
            session.run(
                (
                    """
                UNWIND $files AS file
                MERGE (f:File {path: file.path})
                SET f.language = file.language,
                    f.ecosystem = file.ecosystem,
                    f.name = file.name,
                    f.total_lines = file.total_lines,
                    f.code_lines = file.code_lines,
                    f.method_count = file.method_count,
                    f.class_count = file.class_count,
                    f.interface_count = file.interface_count,
                    f."""
                    + f"{_EMB_PROP}"
                    + """ = CASE WHEN file."""
                    + f"{_EMB_PROP}"
                    + """ IS NOT NULL THEN file."""
                    + f"{_EMB_PROP}"
                    + """ ELSE f."""
                    + f"{_EMB_PROP}"
                    + """ END,
                    f.embedding_type = CASE WHEN file."""
                    + f"{_EMB_PROP}"
                    + """ IS NOT NULL THEN file.embedding_type ELSE f.embedding_type END
                """
                ),
                files=[{**f, _EMB_PROP: f.get(_EMB_PROP)} for f in batch],
            )

    file_dir_rels = []
    from pathlib import Path as _Path

    for file_data in files_data:
        parent_dir = (
            str(_Path(file_data["path"]).parent)
            if _Path(file_data["path"]).parent != _Path(".")
            else ""
        )
        file_dir_rels.append({"file": file_data["path"], "directory": parent_dir})

    if file_dir_rels:
        logger.info(f"Creating {len(file_dir_rels)} file-directory relationships...")
        for i in range(0, len(file_dir_rels), batch_size):
            batch_num = i // batch_size + 1
            batch = file_dir_rels[i : i + batch_size]
            logger.debug(f"Creating file-dir rel batch {batch_num} ({len(batch)} relationships)")
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (d:Directory {path: rel.directory}) "
                "MATCH (f:File {path: rel.file}) "
                "MERGE (d)-[:CONTAINS]->(f)",
                rels=batch,
            )


def create_classes(session: Any, files_data: list[FileData]) -> None:
    batch_size = 1000

    all_classes = []
    all_interfaces = []
    class_inheritance = []
    interface_inheritance = []
    class_implementations = []

    for file_data in files_data:
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

            if class_info.get("extends"):
                class_inheritance.append(
                    {
                        "child": class_info["name"],
                        "child_file": class_info["file"],
                        "parent": class_info["extends"],
                    }
                )

            for interface in class_info.get("implements", []):
                class_implementations.append(
                    {
                        "class": class_info["name"],
                        "class_file": class_info["file"],
                        "interface": interface,
                    }
                )

        for interface_info in file_data.get("interfaces", []):
            interface_node = {
                "name": interface_info["name"],
                "file": interface_info["file"],
                "line": interface_info.get("line"),
                "method_count": interface_info.get("method_count", 0),
                "modifiers": interface_info.get("modifiers", []),
            }
            all_interfaces.append(interface_node)

            for extended_interface in interface_info.get("extends", []):
                interface_inheritance.append(
                    {
                        "child": interface_info["name"],
                        "child_file": interface_info["file"],
                        "parent": extended_interface,
                    }
                )

    if all_classes:
        logger.info(f"Creating {len(all_classes)} class nodes...")
        for i in range(0, len(all_classes), batch_size):
            batch_num = i // batch_size + 1
            batch = all_classes[i : i + batch_size]
            logger.debug(f"Creating class batch {batch_num} ({len(batch)} classes)")
            session.run(
                "UNWIND $classes AS class "
                "MERGE (c:Class {name: class.name, file: class.file}) "
                "SET c.line = class.line, c.estimated_lines = class.estimated_lines, "
                "c.is_abstract = class.is_abstract, c.is_final = class.is_final, "
                "c.modifiers = class.modifiers",
                classes=batch,
            )

    if all_interfaces:
        logger.info(f"Creating {len(all_interfaces)} interface nodes...")
        for i in range(0, len(all_interfaces), batch_size):
            batch_num = i // batch_size + 1
            batch = all_interfaces[i : i + batch_size]
            logger.debug(f"Creating interface batch {batch_num} ({len(batch)} interfaces)")
            session.run(
                "UNWIND $interfaces AS interface "
                "MERGE (i:Interface {name: interface.name, file: interface.file}) "
                "SET i.line = interface.line, i.method_count = interface.method_count, "
                "i.modifiers = interface.modifiers",
                interfaces=batch,
            )

    if class_inheritance:
        logger.info(f"Creating {len(class_inheritance)} class inheritance relationships...")
        for i in range(0, len(class_inheritance), batch_size):
            batch_num = i // batch_size + 1
            batch = class_inheritance[i : i + batch_size]
            logger.debug(
                f"Creating class inheritance batch {batch_num} ({len(batch)} relationships)"
            )
            session.run(
                "UNWIND $inheritance AS rel "
                "MATCH (child:Class {name: rel.child, file: rel.child_file}) "
                "MERGE (parent:Class {name: rel.parent}) "
                "MERGE (child)-[:EXTENDS]->(parent)",
                inheritance=batch,
            )

    if interface_inheritance:
        logger.info(f"Creating {len(interface_inheritance)} interface inheritance relationships...")
        for i in range(0, len(interface_inheritance), batch_size):
            batch_num = i // batch_size + 1
            batch = interface_inheritance[i : i + batch_size]
            logger.debug(
                f"Creating interface inheritance batch {batch_num} ({len(batch)} relationships)"
            )
            session.run(
                "UNWIND $inheritance AS rel "
                "MATCH (child:Interface {name: rel.child, file: rel.child_file}) "
                "MERGE (parent:Interface {name: rel.parent}) "
                "MERGE (child)-[:EXTENDS]->(parent)",
                inheritance=batch,
            )

    if class_implementations:
        logger.info(f"Creating {len(class_implementations)} implementation relationships...")
        for i in range(0, len(class_implementations), batch_size):
            batch_num = i // batch_size + 1
            batch = class_implementations[i : i + batch_size]
            logger.debug(f"Creating implementation batch {batch_num} ({len(batch)} relationships)")
            session.run(
                "UNWIND $implementations AS rel "
                "MATCH (c:Class {name: rel.class, file: rel.class_file}) "
                "MERGE (i:Interface {name: rel.interface}) "
                "MERGE (c)-[:IMPLEMENTS]->(i)",
                implementations=batch,
            )

    file_class_rels = []
    for file_data in files_data:
        for class_info in file_data.get("classes", []):
            file_class_rels.append({"file": file_data["path"], "class": class_info["name"]})

    if file_class_rels:
        logger.info(f"Creating {len(file_class_rels)} file-to-class relationships...")
        for i in range(0, len(file_class_rels), batch_size):
            batch_num = i // batch_size + 1
            batch = file_class_rels[i : i + batch_size]
            logger.debug(
                f"Creating file-class relationship batch {batch_num} ({len(batch)} relationships)"
            )
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (f:File {path: rel.file}) "
                "MATCH (c:Class {name: rel.class, file: rel.file}) "
                "MERGE (f)-[:DEFINES]->(c)",
                rels=batch,
            )

    file_interface_rels = []
    for file_data in files_data:
        for interface_info in file_data.get("interfaces", []):
            file_interface_rels.append(
                {"file": file_data["path"], "interface": interface_info["name"]}
            )

    if file_interface_rels:
        logger.info(f"Creating {len(file_interface_rels)} file-to-interface relationships...")
        for i in range(0, len(file_interface_rels), batch_size):
            batch_num = i // batch_size + 1
            batch = file_interface_rels[i : i + batch_size]
            logger.debug(
                f"Creating file-interface rel batch {batch_num} ({len(batch)} relationships)"
            )
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (f:File {path: rel.file}) "
                "MATCH (i:Interface {name: rel.interface, file: rel.file}) "
                "MERGE (f)-[:DEFINES]->(i)",
                rels=batch,
            )


def create_methods(
    session: Any, files_data: list[FileData], method_embeddings: list[list[float]]
) -> None:
    method_nodes: list[dict[str, Any]] = []
    method_idx = 0
    warned_short = False

    for file_data in files_data:
        for method in file_data["methods"]:
            has_embedding = method_idx < len(method_embeddings)
            if not has_embedding and not warned_short:
                total_methods = sum(len(f.get("methods", [])) for f in files_data)
                logger.warning(
                    "Missing method embedding(s) (%d embeddings for %d methods); leaving embedding unset",
                    len(method_embeddings),
                    total_methods,
                )
                warned_short = True
            emb_value = None
            if has_embedding:
                try:
                    emb = method_embeddings[method_idx]
                    emb_value = emb.tolist() if hasattr(emb, "tolist") else emb  # type: ignore[arg-type]
                except Exception:
                    emb_value = None

            from constants import EMBEDDING_PROPERTY as _EMB_PROP

            method_node = {
                "name": method["name"],
                "file": method["file"],
                "line": method["line"],
                **({_EMB_PROP: emb_value} if has_embedding and emb_value is not None else {}),
                "embedding_type": EMBEDDING_TYPE,
                "estimated_lines": method.get("estimated_lines", 0),
                "is_static": method.get("is_static", False),
                "is_abstract": method.get("is_abstract", False),
                "is_final": method.get("is_final", False),
                "is_private": method.get("is_private", False),
                "is_public": method.get("is_public", False),
                "return_type": method.get("return_type", "void"),
                "modifiers": method.get("modifiers", []),
                "method_signature": method.get("method_signature"),
            }
            if method.get("class_name"):
                method_node["class_name"] = method["class_name"]
                method_node["containing_type"] = method.get("containing_type", "class")

            method_nodes.append(method_node)
            method_idx += 1

    batch_size = _get_database_batch_size(has_embeddings=True)
    total_batches = (len(method_nodes) + batch_size - 1) // batch_size
    logger.info(f"Creating {len(method_nodes)} method nodes in {total_batches} batches...")

    for i in tqdm(
        range(0, len(method_nodes), batch_size),
        total=total_batches,
        desc="Method nodes",
    ):
        batch = method_nodes[i : i + batch_size]

        from constants import EMBEDDING_PROPERTY as _EMB_PROP

        session.run(
            (
                """
                UNWIND $methods AS method
                MERGE (m:Method {method_signature: method.method_signature})
                SET m.name = method.name,
                    m.file = method.file,
                    m.line = method.line,
                """
                + f"m.{_EMB_PROP} = CASE WHEN method.{_EMB_PROP} IS NOT NULL THEN method.{_EMB_PROP} ELSE m.{_EMB_PROP} END, "
                + f"m.embedding_type = CASE WHEN method.{_EMB_PROP} IS NOT NULL THEN method.embedding_type ELSE m.embedding_type END,"
                + """
                    m.estimated_lines = method.estimated_lines,
                    m.is_static = method.is_static,
                    m.is_abstract = method.is_abstract,
                    m.is_final = method.is_final,
                    m.is_private = method.is_private,
                    m.is_public = method.is_public,
                    m.return_type = method.return_type,
                    m.modifiers = method.modifiers,
                    m.id = coalesce(m.id, method.method_signature)
                """
                + (
                    "SET m.class_name = method.class_name, m.containing_type = method.containing_type"
                    if any("class_name" in m for m in batch)
                    else ""
                )
            ),
            methods=batch,
        )

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

    total_rel_batches = (len(method_file_rels) + batch_size - 1) // batch_size
    logger.info(
        "Creating %d method-file relationships in %d batches..."
        % (len(method_file_rels), total_rel_batches)
    )

    for i in tqdm(
        range(0, len(method_file_rels), batch_size),
        total=total_rel_batches,
        desc="Method-File rels",
    ):
        batch = method_file_rels[i : i + batch_size]

        session.run(
            "UNWIND $rels AS rel "
            "MATCH (f:File {path: rel.file_path}) "
            "MATCH (m:Method {name: rel.method_name, file: rel.file_path, line: rel.method_line}) "
            "MERGE (f)-[:DECLARES]->(m)",
            rels=batch,
        )


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


def create_method_calls(session: Any, files_data: list[FileData]) -> None:
    batch_size = 1000
    method_call_rels = []

    for file_data in files_data:
        for method in file_data["methods"]:
            for call in method.get("calls", []):
                method_call_rels.append(
                    {
                        "caller_name": method["name"],
                        "caller_file": method["file"],
                        "caller_line": method["line"],
                        "caller_class": method.get("class_name"),
                        "callee_name": call["method_name"],
                        "callee_class": call["target_class"],
                        "call_type": call["call_type"],
                        "qualifier": call.get("qualifier"),
                    }
                )

    if method_call_rels:
        total_calls = len(method_call_rels)
        logger.info("Processing %d method call relationships...", total_calls)

        same_class_calls = [r for r in method_call_rels if r["call_type"] in ["same_class", "this"]]
        static_calls = [r for r in method_call_rels if r["call_type"] == "static"]
        other_calls = [
            r for r in method_call_rels if r["call_type"] not in ["same_class", "this", "static"]
        ]

        if same_class_calls:
            logger.info("Creating %d same-class method calls...", len(same_class_calls))
            for i in range(0, len(same_class_calls), batch_size):
                batch = same_class_calls[i : i + batch_size]
                session.run(
                    "UNWIND $calls AS call "
                    "MATCH (caller:Method {name: call.caller_name, "
                    "file: call.caller_file, line: call.caller_line}) "
                    "MATCH (callee:Method {name: call.callee_name, class_name: call.callee_class}) "
                    "WHERE caller.file = callee.file "
                    "MERGE (caller)-[:CALLS {type: call.call_type}]->(callee)",
                    calls=batch,
                )

        if static_calls:
            logger.info("Creating %d static method calls...", len(static_calls))
            for i in range(0, len(static_calls), batch_size):
                batch = static_calls[i : i + batch_size]
                session.run(
                    "UNWIND $calls AS call "
                    "MATCH (caller:Method {name: call.caller_name, "
                    "file: call.caller_file, line: call.caller_line}) "
                    "MATCH (callee:Method {name: call.callee_name, class_name: call.callee_class}) "
                    "WHERE callee.is_static = true "
                    "MERGE (caller)-[:CALLS {type: call.call_type, "
                    "qualifier: call.qualifier}]->(callee)",
                    calls=batch,
                )

        if other_calls:
            logger.info("Creating %d other method calls (best effort)...", len(other_calls))

            filtered_calls = []
            for call in other_calls:
                if call.get("callee_name") and len(call["callee_name"]) > 1:
                    filtered_calls.append(call)

            if not filtered_calls:
                logger.info("No valid method calls to process after filtering")
                return

            logger.info("Filtered to %d potentially valid calls", len(filtered_calls))

            batch_size2 = 500
            total_batches = (len(filtered_calls) + batch_size2 - 1) // batch_size2
            successful_calls = 0
            failed_batches = 0

            for i in tqdm(
                range(0, len(filtered_calls), batch_size2),
                total=total_batches,
                desc="Other calls",
            ):
                batch = filtered_calls[i : i + batch_size2]
                try:
                    result = session.run(
                        """
                        UNWIND $calls AS call
                        MATCH (caller:Method {name: call.caller_name, file: call.caller_file, line: call.caller_line})
                        WHERE EXISTS {
                            MATCH (callee:Method {name: call.callee_name})
                            WHERE callee.name = call.callee_name
                        }
                        WITH caller, call
                        MATCH (callee:Method {name: call.callee_name})
                        WITH caller, callee, call
                        LIMIT 1000
                        MERGE (caller)-[:CALLS {type: call.call_type, qualifier: call.qualifier}]->(callee)
                        RETURN count(*) as created
                        """,
                        calls=batch,
                    )
                    created = result.single()["created"]
                    successful_calls += created
                except Exception as e:
                    failed_batches += 1
                    logger.warning(f"Other calls batch failed (continuing): {e}")
                    if failed_batches > 5:
                        logger.error(
                            "Too many failed batches, stopping other method calls processing"
                        )
                        break

            logger.info(
                f"Other method calls completed: {successful_calls} relationships created, "
                f"{failed_batches} batches failed"
            )


def bulk_create_nodes_and_relationships(
    session: Any,
    files_data: list[FileData],
    file_embeddings: list[list[float]],
    method_embeddings: list[list[float]],
    dependency_versions: dict[str, str] | None = None,
) -> None:
    create_directories(session, files_data)
    create_files(session, files_data, file_embeddings)
    create_classes(session, files_data)
    create_methods(session, files_data, method_embeddings)
    create_imports(session, files_data, dependency_versions)
    create_method_calls(session, files_data)
    logger.info("Bulk creation completed!")
