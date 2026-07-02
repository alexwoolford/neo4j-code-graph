#!/usr/bin/env python3

from __future__ import annotations

import logging
from typing import Any, cast

try:
    from src.utils.batching import get_database_batch_size  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from utils.batching import get_database_batch_size  # type: ignore

try:
    from src.utils.progress import progress_range  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from utils.progress import progress_range  # type: ignore

logger = logging.getLogger(__name__)


def _get_database_batch_size(
    has_embeddings: bool = False, estimated_size_mb: int | None = None
) -> int:
    return get_database_batch_size(
        has_embeddings=has_embeddings, estimated_size_mb=estimated_size_mb
    )


def create_directories(session: Any, files_data: list[dict[str, Any]]) -> None:
    batch_size = 1000

    directories: set[str] = set()
    for file_data in files_data:
        from pathlib import Path

        path_parts = Path(file_data["path"]).parent.parts
        # Do NOT include the empty root path; only real directories
        for i in range(1, len(path_parts) + 1):
            dir_path = str(Path(*path_parts[:i]))
            directories.add(dir_path)

    directories_list: list[str] = list(directories)
    if directories_list:
        logger.info(f"Creating {len(directories_list)} directory nodes...")
        for i in progress_range(0, len(directories_list), batch_size, desc="Directory nodes"):
            batch_num = i // batch_size + 1
            batch = directories_list[i : i + batch_size]
            logger.debug(f"Creating directory batch {batch_num} ({len(batch)} directories)")
            session.run(
                "UNWIND $directories AS dir_path MERGE (:Directory {path: dir_path})",
                directories=batch,
            )

    dir_relationships: list[dict[str, str]] = []
    from pathlib import Path as _P

    for directory in directories:
        if directory:
            parent = str(_P(directory).parent) if _P(directory).parent != _P(".") else ""
            # Skip relationships whose parent is the empty root; we no longer create that node
            if parent:
                dir_relationships.append({"parent": parent, "child": directory})

    if dir_relationships:
        logger.info(f"Creating {len(dir_relationships)} directory relationships...")
        for i in progress_range(0, len(dir_relationships), batch_size, desc="Dir rels"):
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


def create_files(session: Any, files_data: list[dict[str, Any]]) -> None:
    batch_size = _get_database_batch_size(has_embeddings=False)

    file_nodes: list[dict[str, Any]] = []
    for file_data in files_data:
        from pathlib import Path as _Path

        file_path_str = file_data["path"]
        file_name_only = _Path(file_path_str).name if file_path_str else file_path_str
        file_node = {
            "path": file_path_str,
            "name": file_name_only,
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
        total_batches = (len(file_nodes) + batch_size - 1) // batch_size
        for i in progress_range(
            0, len(file_nodes), batch_size, total=total_batches, desc="File nodes"
        ):
            batch_num = i // batch_size + 1
            batch = file_nodes[i : i + batch_size]
            logger.debug(f"Creating file batch {batch_num} ({len(batch)} files)")
            session.run(
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
                    f.interface_count = file.interface_count
                """,
                files=batch,
            )

    file_dir_rels: list[dict[str, str]] = []
    from pathlib import Path as _Path

    for file_data in files_data:
        parent_dir = (
            str(_Path(file_data["path"]).parent)
            if _Path(file_data["path"]).parent != _Path(".")
            else ""
        )
        # Skip root-level files; they have no containing directory node
        if parent_dir:
            file_dir_rels.append({"file": file_data["path"], "directory": parent_dir})

    if file_dir_rels:
        logger.info(f"Creating {len(file_dir_rels)} file-directory relationships...")
        for i in progress_range(0, len(file_dir_rels), batch_size, desc="File->Dir rels"):
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


def create_classes(session: Any, files_data: list[dict[str, Any]]) -> None:
    batch_size = 1000

    all_classes = []
    all_interfaces = []
    class_inheritance = []
    interface_inheritance = []
    class_implementations = []

    # Precompute quick lookups for interface locations to improve exact matching
    interface_name_to_file: dict[str, str] = {}
    for fd in files_data:
        for iface in fd.get("interfaces", []) or []:
            name = iface.get("name")
            fpath = iface.get("file")
            if isinstance(name, str) and isinstance(fpath, str):
                interface_name_to_file.setdefault(name, fpath)

    for file_data in files_data:
        for class_info in file_data.get("classes", []):
            class_node = {
                "name": class_info["name"],
                "file": class_info["file"],
                "package": class_info.get("package"),
                "line": class_info.get("line"),
                "estimated_lines": class_info.get("estimated_lines", 0),
                "is_abstract": class_info.get("is_abstract", False),
                "is_final": class_info.get("is_final", False),
                "modifiers": class_info.get("modifiers", []),
                # B1: kind in {class, record, enum} drives secondary :Record / :Enum labels
                "kind": class_info.get("kind") or class_info.get("type") or "class",
            }
            all_classes.append(class_node)

            if class_info.get("extends"):
                class_inheritance.append(
                    {
                        "child": class_info["name"],
                        "child_file": class_info["file"],
                        "child_package": class_info.get("package"),
                        "parent": class_info["extends"],
                        "parent_package": class_info.get("extends_package"),
                    }
                )

            # Build IMPLEMENTS relationships, capturing interface file/package when determinable
            for idx, interface_name in enumerate(class_info.get("implements", [])):
                # Try to resolve interface file from the same file_data block
                inferred_iface_file = None
                for iface in file_data.get("interfaces", []):
                    if iface.get("name") == interface_name:
                        inferred_iface_file = iface.get("file")
                        break

                class_implementations.append(
                    {
                        "class": class_info["name"],
                        "class_file": class_info["file"],
                        "class_package": class_info.get("package"),
                        "interface": interface_name,
                        "interface_file": inferred_iface_file,
                        "interface_package": (
                            (class_info.get("implements_packages") or [None])[idx]
                            if isinstance(class_info.get("implements_packages"), list)
                            else class_info.get("implements_packages")
                        ),
                    }
                )

        for interface_info in file_data.get("interfaces", []):
            interface_node = {
                "name": interface_info["name"],
                "file": interface_info["file"],
                "package": interface_info.get("package"),
                "line": interface_info.get("line"),
                "method_count": interface_info.get("method_count", 0),
                "modifiers": interface_info.get("modifiers", []),
            }
            all_interfaces.append(interface_node)

            for idx, extended_interface in enumerate(interface_info.get("extends", [])):
                interface_inheritance.append(
                    {
                        "child": interface_info["name"],
                        "child_file": interface_info["file"],
                        "child_package": interface_info.get("package"),
                        "parent": extended_interface,
                        "parent_file": interface_name_to_file.get(extended_interface),
                        "parent_package": (
                            (interface_info.get("extends_packages") or [None])[idx]
                            if isinstance(interface_info.get("extends_packages"), list)
                            else interface_info.get("extends_packages")
                        ),
                    }
                )

    if all_classes:
        logger.info(f"Creating {len(all_classes)} class nodes...")
        for i in progress_range(0, len(all_classes), batch_size, desc="Class nodes"):
            batch_num = i // batch_size + 1
            batch = all_classes[i : i + batch_size]
            logger.debug(f"Creating class batch {batch_num} ({len(batch)} classes)")
            session.run(
                "UNWIND $classes AS class "
                "MERGE (c:Class {name: class.name, file: class.file}) "
                "SET c.line = class.line, c.estimated_lines = class.estimated_lines, "
                "c.is_abstract = class.is_abstract, c.is_final = class.is_final, "
                "c.modifiers = class.modifiers, c.package = class.package, "
                "c.kind = coalesce(class.kind, 'class') "
                # Add a secondary label so analysts can MATCH (:Record) / (:Enum) cleanly.
                "WITH c, class "
                "FOREACH (_ IN CASE WHEN class.kind = 'record' THEN [1] ELSE [] END | SET c:Record) "
                "FOREACH (_ IN CASE WHEN class.kind = 'enum'   THEN [1] ELSE [] END | SET c:Enum)",
                classes=batch,
            )

    if all_interfaces:
        logger.info(f"Creating {len(all_interfaces)} interface nodes...")
        for i in progress_range(0, len(all_interfaces), batch_size, desc="Interface nodes"):
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

    # Package -> Class relationships (and Package nodes)
    package_class_rels: list[dict[str, str]] = []
    for file_data in files_data:
        for class_info in file_data.get("classes", []):
            pkg = class_info.get("package")
            if pkg:
                package_class_rels.append(
                    {"package": pkg, "name": class_info["name"], "file": class_info["file"]}
                )

    if package_class_rels:
        logger.info(f"Linking {len(package_class_rels)} classes to Package nodes...")
        for i in progress_range(0, len(package_class_rels), batch_size, desc="Package->Class rels"):
            batch = package_class_rels[i : i + batch_size]
            session.run(
                """
                UNWIND $rels AS r
                MERGE (p:Package {name:r.package})
                WITH p, r
                MATCH (c:Class {name:r.name, file:r.file})
                MERGE (p)-[:CONTAINS]->(c)
                """,
                rels=batch,
            )

    if class_inheritance:
        logger.info(f"Creating {len(class_inheritance)} class inheritance relationships...")
        for i in progress_range(0, len(class_inheritance), batch_size, desc="Class inherits"):
            batch_num = i // batch_size + 1
            batch = class_inheritance[i : i + batch_size]
            logger.debug(
                f"Creating class inheritance batch {batch_num} ({len(batch)} relationships)"
            )
            session.run(
                """
                UNWIND $inheritance AS rel
                MATCH (child:Class {name: rel.child, file: rel.child_file})
                OPTIONAL MATCH (parentExact:Class {name: rel.parent, package: coalesce(rel.parent_package, rel.child_package)})
                WITH child, rel, parentExact
                OPTIONAL MATCH (parentAny:Class {name: rel.parent})
                WITH child, parentExact, collect(parentAny) AS anyParents
                WITH child,
                     CASE
                       WHEN parentExact IS NOT NULL THEN parentExact
                       WHEN size(anyParents) = 1 THEN head(anyParents)
                       ELSE NULL
                     END AS parent
                WHERE parent IS NOT NULL
                MERGE (child)-[:EXTENDS]->(parent)
                """,
                inheritance=batch,
            )

    if interface_inheritance:
        logger.info(f"Creating {len(interface_inheritance)} interface inheritance relationships...")
        for i in progress_range(0, len(interface_inheritance), batch_size, desc="Iface inherits"):
            batch_num = i // batch_size + 1
            batch = interface_inheritance[i : i + batch_size]
            logger.debug(
                f"Creating interface inheritance batch {batch_num} ({len(batch)} relationships)"
            )
            session.run(
                """
                UNWIND $inheritance AS rel
                MATCH (child:Interface {name: rel.child, file: rel.child_file})
                OPTIONAL MATCH (parentExactPkg:Interface {name: rel.parent, package: coalesce(rel.parent_package, rel.child_package)})
                OPTIONAL MATCH (parentExactFile:Interface {name: rel.parent, file: rel.parent_file})
                WITH child, rel, coalesce(parentExactPkg, parentExactFile) AS parentExact
                OPTIONAL MATCH (parentAny:Interface {name: rel.parent})
                WITH child, parentExact, collect(parentAny) AS anyParents
                WITH child,
                     CASE
                       WHEN parentExact IS NOT NULL THEN parentExact
                       WHEN size(anyParents) = 1 THEN head(anyParents)
                       ELSE NULL
                     END AS parent
                WHERE parent IS NOT NULL
                MERGE (child)-[:EXTENDS]->(parent)
                """,
                inheritance=batch,
            )

    if class_implementations:
        logger.info(f"Creating {len(class_implementations)} implementation relationships...")
        for i in progress_range(0, len(class_implementations), batch_size, desc="Implements"):
            batch_num = i // batch_size + 1
            batch = class_implementations[i : i + batch_size]
            logger.debug(f"Creating implementation batch {batch_num} ({len(batch)} relationships)")
            session.run(
                """
                UNWIND $implementations AS rel
                MATCH (c:Class {name: rel.class, file: rel.class_file})
                // Prefer exact package match when provided
                OPTIONAL MATCH (iExactPkg:Interface {name: rel.interface, package: coalesce(rel.interface_package, rel.class_package)})
                // Also try exact file match when available
                OPTIONAL MATCH (iExactFile:Interface {name: rel.interface, file: rel.interface_file})
                WITH c, rel, coalesce(iExactPkg, iExactFile) AS iExact
                OPTIONAL MATCH (iAny:Interface {name: rel.interface})
                WITH c, iExact, collect(iAny) AS anyIfaces
                WITH c,
                     CASE
                       WHEN iExact IS NOT NULL THEN iExact
                       WHEN size(anyIfaces) = 1 THEN head(anyIfaces)
                       ELSE NULL
                     END AS i
                WHERE i IS NOT NULL
                MERGE (c)-[:IMPLEMENTS]->(i)
                """,
                implementations=batch,
            )

    file_class_rels = []
    for file_data in files_data:
        for class_info in file_data.get("classes", []):
            file_class_rels.append({"file": file_data["path"], "class": class_info["name"]})

    if file_class_rels:
        logger.info(f"Creating {len(file_class_rels)} file-to-class relationships...")
        for i in progress_range(0, len(file_class_rels), batch_size, desc="File->Class rels"):
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
        for i in progress_range(0, len(file_interface_rels), batch_size, desc="File->Iface rels"):
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


def create_methods(session: Any, files_data: list[dict[str, Any]]) -> None:
    """Delegate to writers.methods.create_methods to avoid duplication."""
    try:
        from src.data.writers.methods import (
            create_methods as _create_methods,  # type: ignore[attr-defined]
        )
    except Exception:  # pragma: no cover
        from data.writers.methods import create_methods as _create_methods  # type: ignore

    _create_methods(session, files_data)


def create_imports(
    session: Any,
    files_data: list[dict[str, Any]],
    dependency_versions: dict[str, str] | None = None,
) -> None:
    """Delegate to writers.imports.create_imports to avoid duplication."""
    try:
        from src.data.writers.imports import (
            create_imports as _create_imports,  # type: ignore[attr-defined]
        )
    except Exception:  # pragma: no cover
        from data.writers.imports import create_imports as _create_imports  # type: ignore

    _create_imports(session, files_data, dependency_versions)


def create_method_calls(session: Any, files_data: list[dict[str, Any]]) -> None:
    """Delegate to writers.methods.create_method_calls to avoid duplication."""
    try:
        from src.data.writers.methods import (
            create_method_calls as _create_method_calls,  # type: ignore[attr-defined]
        )
    except Exception:  # pragma: no cover
        from data.writers.methods import create_method_calls as _create_method_calls  # type: ignore

    _create_method_calls(session, files_data)


def bulk_create_nodes_and_relationships(
    session: Any,
    files_data: list[dict[str, Any]],
    dependency_versions: dict[str, str] | None = None,
) -> None:
    create_directories(session, files_data)
    create_files(session, files_data)
    create_classes(session, files_data)
    create_methods(session, files_data)
    # B1 schema additions: Field, Annotation, Exception nodes + NESTED_IN edges.
    # Must run after create_classes/create_methods (they reference Method/Class
    # nodes via MATCH).
    create_fields(session, files_data)
    create_annotations(session, files_data)
    create_throws(session, files_data)
    create_nested_class_links(session, files_data)
    # Create Doc nodes (docstrings/comments) and HAS_DOC relationships
    create_docs(session, files_data)
    create_imports(session, files_data, dependency_versions)
    create_method_calls(session, files_data)
    logger.info("Bulk creation completed!")


def create_docs(session: Any, files_data: list[dict[str, Any]]) -> None:
    """Create Doc nodes from extracted docs in files_data."""
    docs: list[dict[str, Any]] = []
    rels_file: list[dict[str, str]] = []
    rels_method: list[dict[str, str]] = []
    rels_class: list[dict[str, str]] = []

    import hashlib as _hash

    for fd in files_data:
        doc_items = cast(list[dict[str, Any]], fd.get("docs", []) or [])
        for d in doc_items:
            text_val = d.get("text", "")
            text: str = text_val if isinstance(text_val, str) else ""
            # Stable id: sha256(file + kind + start + end + first 64 chars)
            basis = f"{d.get('file')}|{d.get('kind')}|{d.get('start_line')}|{d.get('end_line')}|{text[:64]}"
            doc_id = _hash.sha256(basis.encode("utf-8", errors="ignore")).hexdigest()
            docs.append(
                {
                    "id": doc_id,
                    "file": d.get("file"),
                    "kind": d.get("kind"),
                    "language": d.get("language"),
                    "start_line": d.get("start_line"),
                    "end_line": d.get("end_line"),
                    "text": text[:1000],
                    "scope": d.get("scope"),
                }
            )
            file_path_val = d.get("file")
            if isinstance(file_path_val, str):
                rels_file.append({"file": file_path_val, "id": doc_id})
            # Method attachment if available
            sig_val: str | None = (
                d.get("method_signature") if isinstance(d.get("method_signature"), str) else None
            )
            if sig_val:
                rels_method.append({"sig": sig_val, "id": doc_id})
            cls_val = d.get("class_name")
            if isinstance(cls_val, str) and not sig_val and isinstance(file_path_val, str):
                rels_class.append({"file": file_path_val, "name": cls_val, "id": doc_id})

    if docs:
        logger.info("Creating %d Doc nodes...", len(docs))
        batch_size = 1000
        for i in progress_range(0, len(docs), batch_size, desc="Doc nodes"):
            batch = docs[i : i + batch_size]
            session.run(
                """
                UNWIND $docs AS d
                MERGE (x:Doc {id: d.id})
                SET x.file = d.file,
                    x.kind = d.kind,
                    x.language = d.language,
                    x.start_line = d.start_line,
                    x.end_line = d.end_line,
                    x.text = d.text,
                    x.scope = d.scope
                """,
                docs=batch,
            )
    if rels_file:
        for i in progress_range(0, len(rels_file), 2000, desc="File->Doc rels"):
            batch = rels_file[i : i + 2000]
            session.run(
                """
                UNWIND $rels AS r
                MATCH (f:File {path:r.file})
                MATCH (d:Doc {id:r.id})
                MERGE (f)-[:HAS_DOC]->(d)
                """,
                rels=batch,
            )
    if rels_method:
        for i in progress_range(0, len(rels_method), 2000, desc="Method->Doc rels"):
            batch = rels_method[i : i + 2000]
            session.run(
                """
                UNWIND $rels AS r
                MATCH (m:Method {method_signature:r.sig})
                MATCH (d:Doc {id:r.id})
                MERGE (m)-[:HAS_DOC]->(d)
                """,
                rels=batch,
            )
    if rels_class:
        for i in progress_range(0, len(rels_class), 2000, desc="Class->Doc rels"):
            batch = rels_class[i : i + 2000]
            session.run(
                """
                UNWIND $rels AS r
                MATCH (c:Class {name:r.name, file:r.file})
                MATCH (d:Doc {id:r.id})
                MERGE (c)-[:HAS_DOC]->(d)
                """,
                rels=batch,
            )


def create_fields(session: Any, files_data: list[dict[str, Any]]) -> None:
    """B1: persist Field nodes and DECLARES_FIELD edges from owning type to field.

    A Field is keyed by (owner_name, name, file) -- this matches typical Java
    semantics where field names are unique within their declaring type.
    """
    field_records: list[dict[str, Any]] = []
    for file_data in files_data:
        for f in file_data.get("fields", []) or []:
            if not f.get("name") or not f.get("owner_name"):
                continue
            field_records.append(
                {
                    "name": f["name"],
                    "owner_name": f["owner_name"],
                    "owner_kind": f.get("owner_kind") or "class",
                    "file": f.get("file") or file_data.get("path"),
                    "package": f.get("package"),
                    "line": f.get("line"),
                    "type": f.get("type") or "",
                    "type_package": f.get("type_package"),
                    "is_static": bool(f.get("is_static", False)),
                    "is_final": bool(f.get("is_final", False)),
                    "is_private": bool(f.get("is_private", False)),
                    "is_public": bool(f.get("is_public", False)),
                    "is_protected": bool(f.get("is_protected", False)),
                    "is_package_private": bool(f.get("is_package_private", False)),
                    "is_volatile": bool(f.get("is_volatile", False)),
                    "is_transient": bool(f.get("is_transient", False)),
                }
            )

    if not field_records:
        return

    logger.info(f"Creating {len(field_records)} Field nodes...")
    batch_size = 1000
    for i in range(0, len(field_records), batch_size):
        batch = field_records[i : i + batch_size]
        # Owner can be Class, Interface, or any other type-declaring node. Match
        # broadly so records and enums (which carry the secondary :Record / :Enum
        # label on top of :Class) are also picked up.
        session.run(
            """
            UNWIND $fields AS f
            MERGE (fld:Field {owner_name: f.owner_name, name: f.name, file: f.file})
            SET fld.line = f.line,
                fld.package = f.package,
                fld.type = f.type,
                fld.type_package = f.type_package,
                fld.owner_kind = f.owner_kind,
                fld.is_static = f.is_static,
                fld.is_final = f.is_final,
                fld.is_private = f.is_private,
                fld.is_public = f.is_public,
                fld.is_protected = f.is_protected,
                fld.is_package_private = f.is_package_private,
                fld.is_volatile = f.is_volatile,
                fld.is_transient = f.is_transient
            WITH fld, f
            // Owner is either a Class (incl. records/enums via secondary label)
            // or an Interface (rare: interface constants).
            OPTIONAL MATCH (cls:Class {name: f.owner_name, file: f.file})
            OPTIONAL MATCH (iface:Interface {name: f.owner_name, file: f.file})
            WITH fld, coalesce(cls, iface) AS owner
            WHERE owner IS NOT NULL
            MERGE (owner)-[:DECLARES_FIELD]->(fld)
            """,
            fields=batch,
        )


def create_annotations(session: Any, files_data: list[dict[str, Any]]) -> None:
    """B1: persist Annotation nodes (deduped by name) and ANNOTATED edges.

    Annotation names are deduped across the whole codebase (e.g. all uses of
    @Override merge to one Annotation node). Each ANNOTATED edge stores the raw
    text of the application so analysts can recover argument values.
    """
    type_links: list[dict[str, Any]] = []
    method_links: list[dict[str, Any]] = []
    field_links: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for file_data in files_data:
        for c in file_data.get("classes", []) or []:
            for ann in c.get("annotations", []) or []:
                name = ann.get("name") or ""
                if not name:
                    continue
                seen_names.add(name)
                type_links.append(
                    {
                        "owner_name": c["name"],
                        "owner_file": c.get("file") or file_data.get("path"),
                        "ann_name": name,
                        "ann_package": ann.get("fqn_package"),
                        "raw": ann.get("raw") or "",
                    }
                )
        for i in file_data.get("interfaces", []) or []:
            for ann in i.get("annotations", []) or []:
                name = ann.get("name") or ""
                if not name:
                    continue
                seen_names.add(name)
                type_links.append(
                    {
                        "owner_name": i["name"],
                        "owner_file": i.get("file") or file_data.get("path"),
                        "ann_name": name,
                        "ann_package": ann.get("fqn_package"),
                        "raw": ann.get("raw") or "",
                    }
                )
        for m in file_data.get("methods", []) or []:
            sig = m.get("method_signature")
            if not sig:
                continue
            for ann in m.get("annotations", []) or []:
                name = ann.get("name") or ""
                if not name:
                    continue
                seen_names.add(name)
                method_links.append(
                    {
                        "method_signature": sig,
                        "ann_name": name,
                        "ann_package": ann.get("fqn_package"),
                        "raw": ann.get("raw") or "",
                    }
                )
        for f in file_data.get("fields", []) or []:
            owner = f.get("owner_name")
            fname = f.get("name")
            ffile = f.get("file") or file_data.get("path")
            if not (owner and fname and ffile):
                continue
            for ann in f.get("annotations", []) or []:
                name = ann.get("name") or ""
                if not name:
                    continue
                seen_names.add(name)
                field_links.append(
                    {
                        "owner_name": owner,
                        "field_name": fname,
                        "file": ffile,
                        "ann_name": name,
                        "ann_package": ann.get("fqn_package"),
                        "raw": ann.get("raw") or "",
                    }
                )

    if not seen_names:
        return

    logger.info(
        f"Creating {len(seen_names)} Annotation nodes "
        f"({len(type_links)} type, {len(method_links)} method, {len(field_links)} field links)..."
    )
    annotation_nodes = [{"name": n} for n in sorted(seen_names)]
    session.run(
        "UNWIND $anns AS a MERGE (:Annotation {name: a.name})",
        anns=annotation_nodes,
    )

    if type_links:
        session.run(
            """
            UNWIND $links AS l
            MATCH (a:Annotation {name: l.ann_name})
            OPTIONAL MATCH (cls:Class {name: l.owner_name, file: l.owner_file})
            OPTIONAL MATCH (iface:Interface {name: l.owner_name, file: l.owner_file})
            WITH a, l, coalesce(cls, iface) AS owner
            WHERE owner IS NOT NULL
            MERGE (owner)-[r:ANNOTATED]->(a)
            SET r.raw = l.raw, r.ann_package = l.ann_package
            """,
            links=type_links,
        )
    if method_links:
        session.run(
            """
            UNWIND $links AS l
            MATCH (m:Method {method_signature: l.method_signature})
            MATCH (a:Annotation {name: l.ann_name})
            MERGE (m)-[r:ANNOTATED]->(a)
            SET r.raw = l.raw, r.ann_package = l.ann_package
            """,
            links=method_links,
        )
    if field_links:
        session.run(
            """
            UNWIND $links AS l
            MATCH (fld:Field {owner_name: l.owner_name, name: l.field_name, file: l.file})
            MATCH (a:Annotation {name: l.ann_name})
            MERGE (fld)-[r:ANNOTATED]->(a)
            SET r.raw = l.raw, r.ann_package = l.ann_package
            """,
            links=field_links,
        )


def create_throws(session: Any, files_data: list[dict[str, Any]]) -> None:
    """B1: persist Exception nodes (deduped by simple name) and THROWS edges.

    Exception nodes are minimal -- name + optional package. They're not linked
    to Class nodes (we don't know if the exception is project-internal); add
    that linkage post-hoc via Cypher if useful.
    """
    seen: set[str] = set()
    links: list[dict[str, Any]] = []
    for file_data in files_data:
        for m in file_data.get("methods", []) or []:
            sig = m.get("method_signature")
            if not sig:
                continue
            for t in m.get("throws", []) or []:
                name = t.get("type") or ""
                if not name:
                    continue
                seen.add(name)
                links.append(
                    {
                        "method_signature": sig,
                        "exception_name": name,
                        "exception_package": t.get("type_package"),
                    }
                )
    if not seen:
        return

    logger.info(f"Creating {len(seen)} Exception nodes ({len(links)} THROWS edges)...")
    nodes = [{"name": n} for n in sorted(seen)]
    session.run("UNWIND $exs AS e MERGE (:Exception {name: e.name})", exs=nodes)
    session.run(
        """
        UNWIND $links AS l
        MATCH (m:Method {method_signature: l.method_signature})
        MATCH (e:Exception {name: l.exception_name})
        MERGE (m)-[r:THROWS]->(e)
        SET r.exception_package = l.exception_package
        """,
        links=links,
    )


def create_nested_class_links(session: Any, files_data: list[dict[str, Any]]) -> None:
    """B1: NESTED_IN edges from inner/nested classes to their lexical parent.

    Nesting is detected at parse time (`enclosing_name` on the class info dict).
    The parent must live in the same file (Java's lexical-nesting rule).
    """
    rels: list[dict[str, Any]] = []
    for file_data in files_data:
        all_types = list(file_data.get("classes", []) or []) + list(
            file_data.get("interfaces", []) or []
        )
        for t in all_types:
            enc = t.get("enclosing_name")
            if not enc or not t.get("name") or not t.get("file"):
                continue
            rels.append(
                {
                    "child_name": t["name"],
                    "child_file": t["file"],
                    "parent_name": enc,
                    "parent_file": t["file"],
                }
            )

    if not rels:
        return

    logger.info(f"Creating {len(rels)} NESTED_IN relationships...")
    session.run(
        """
        UNWIND $rels AS r
        OPTIONAL MATCH (childC:Class {name: r.child_name, file: r.child_file})
        OPTIONAL MATCH (childI:Interface {name: r.child_name, file: r.child_file})
        OPTIONAL MATCH (parentC:Class {name: r.parent_name, file: r.parent_file})
        OPTIONAL MATCH (parentI:Interface {name: r.parent_name, file: r.parent_file})
        WITH coalesce(childC, childI) AS child, coalesce(parentC, parentI) AS parent
        WHERE child IS NOT NULL AND parent IS NOT NULL
        MERGE (child)-[:NESTED_IN]->(parent)
        """,
        rels=rels,
    )
