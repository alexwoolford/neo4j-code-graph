#!/usr/bin/env python3

from __future__ import annotations

import logging
from typing import Any, cast

try:
    from src.constants import EMBEDDING_TYPE  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from constants import EMBEDDING_TYPE  # type: ignore

try:
    from src.utils.batching import get_database_batch_size  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from utils.batching import get_database_batch_size  # type: ignore

try:
    from src.utils.progress import progress_range  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from utils.progress import progress_range  # type: ignore

try:
    from src.constants import EMBEDDING_PROPERTY as EMB_PROP  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from constants import EMBEDDING_PROPERTY as EMB_PROP  # type: ignore

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


def create_files(
    session: Any, files_data: list[dict[str, Any]], file_embeddings: list[list[float]]
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

        file_node = {
            "path": file_path_str,
            "name": file_name_only,
            **({EMB_PROP: emb_value} if has_embedding and emb_value is not None else {}),
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
        total_batches = (len(file_nodes) + batch_size - 1) // batch_size
        for i in progress_range(
            0, len(file_nodes), batch_size, total=total_batches, desc="File nodes"
        ):
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
                    + f"{EMB_PROP}"
                    + """ = CASE WHEN file."""
                    + f"{EMB_PROP}"
                    + """ IS NOT NULL THEN file."""
                    + f"{EMB_PROP}"
                    + """ ELSE f."""
                    + f"{EMB_PROP}"
                    + """ END,
                    f.embedding_type = CASE WHEN file."""
                    + f"{EMB_PROP}"
                    + """ IS NOT NULL THEN file.embedding_type ELSE f.embedding_type END
                """
                ),
                files=[{**f, EMB_PROP: f.get(EMB_PROP)} for f in batch],
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
        for i in progress_range(0, len(all_classes), batch_size, desc="Class nodes"):
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

    if class_inheritance:
        logger.info(f"Creating {len(class_inheritance)} class inheritance relationships...")
        for i in progress_range(0, len(class_inheritance), batch_size, desc="Class inherits"):
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
        for i in progress_range(0, len(interface_inheritance), batch_size, desc="Iface inherits"):
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
        for i in progress_range(0, len(class_implementations), batch_size, desc="Implements"):
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


def create_methods(
    session: Any, files_data: list[dict[str, Any]], method_embeddings: list[list[float]]
) -> None:
    """Delegate to writers.methods.create_methods to avoid duplication."""
    try:
        from src.data.writers.methods import (
            create_methods as _create_methods,  # type: ignore[attr-defined]
        )
    except Exception:  # pragma: no cover
        from data.writers.methods import create_methods as _create_methods  # type: ignore

    _create_methods(session, files_data, method_embeddings)


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
    file_embeddings: list[list[float]],
    method_embeddings: list[list[float]],
    dependency_versions: dict[str, str] | None = None,
) -> None:
    create_directories(session, files_data)
    create_files(session, files_data, file_embeddings)
    create_classes(session, files_data)
    create_methods(session, files_data, method_embeddings)
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
                    x.text = d.text
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
