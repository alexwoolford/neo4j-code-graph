#!/usr/bin/env python3

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

try:
    _constants = import_module("src.constants")
except Exception:  # pragma: no cover
    _constants = import_module("constants")
EMBEDDING_TYPE = _constants.EMBEDDING_TYPE
EMBEDDING_PROPERTY_NAME = _constants.EMBEDDING_PROPERTY

try:
    _batching = import_module("src.utils.batching")
except Exception:  # pragma: no cover
    _batching = import_module("utils.batching")
get_database_batch_size = _batching.get_database_batch_size

try:
    _progress = import_module("src.utils.progress")
except Exception:  # pragma: no cover
    _progress = import_module("utils.progress")
progress_range = _progress.progress_range

logger = logging.getLogger(__name__)


def create_methods(
    session: Any, files_data: list[dict[str, Any]], method_embeddings: list[list[float]]
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

            method_node = {
                "name": method["name"],
                "file": method["file"],
                "line": method["line"],
                **(
                    {EMBEDDING_PROPERTY_NAME: emb_value}
                    if has_embedding and emb_value is not None
                    else {}
                ),
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
                "cyclomatic_complexity": method.get("cyclomatic_complexity", 1),
            }
            if method.get("class_name"):
                method_node["class_name"] = method["class_name"]
                method_node["containing_type"] = method.get("containing_type", "class")

            method_nodes.append(method_node)
            method_idx += 1

    batch_size = get_database_batch_size(has_embeddings=True)
    total_batches = (len(method_nodes) + batch_size - 1) // batch_size
    logger.info(f"Creating {len(method_nodes)} method nodes in {total_batches} batches...")

    for i in progress_range(
        0, len(method_nodes), batch_size, total=total_batches, desc="Method nodes"
    ):
        batch = method_nodes[i : i + batch_size]

        session.run(
            (
                """
                UNWIND $methods AS method
                MERGE (m:Method {method_signature: method.method_signature})
                SET m.name = method.name,
                    m.file = method.file,
                    m.line = method.line,
                """
                + f"m.{EMBEDDING_PROPERTY_NAME} = CASE WHEN method.{EMBEDDING_PROPERTY_NAME} IS NOT NULL THEN method.{EMBEDDING_PROPERTY_NAME} ELSE m.{EMBEDDING_PROPERTY_NAME} END, "
                + f"m.embedding_type = CASE WHEN method.{EMBEDDING_PROPERTY_NAME} IS NOT NULL THEN method.embedding_type ELSE m.embedding_type END,"
                + """
                    m.estimated_lines = method.estimated_lines,
                    m.is_static = method.is_static,
                    m.is_abstract = method.is_abstract,
                    m.is_final = method.is_final,
                    m.is_private = method.is_private,
                    m.is_public = method.is_public,
                    m.return_type = method.return_type,
                    m.modifiers = method.modifiers,
                    m.cyclomatic_complexity = method.cyclomatic_complexity,
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

    for i in progress_range(
        0, len(method_file_rels), batch_size, total=total_rel_batches, desc="Method-File rels"
    ):
        batch = method_file_rels[i : i + batch_size]

        session.run(
            "UNWIND $rels AS rel "
            "MATCH (f:File {path: rel.file_path}) "
            "MATCH (m:Method {name: rel.method_name, file: rel.file_path, line: rel.method_line}) "
            "MERGE (f)-[:DECLARES]->(m)",
            rels=batch,
        )

    method_class_rels = []
    method_interface_rels = []

    for file_data in files_data:
        for method in file_data["methods"]:
            if method.get("class_name"):
                if method.get("containing_type") == "interface":
                    method_interface_rels.append(
                        {
                            "method_name": method["name"],
                            "method_file": method["file"],
                            "method_line": method["line"],
                            "interface_name": method["class_name"],
                        }
                    )
                else:
                    method_class_rels.append(
                        {
                            "method_name": method["name"],
                            "method_file": method["file"],
                            "method_line": method["line"],
                            "class_name": method["class_name"],
                        }
                    )

    if method_class_rels:
        logger.info("Creating %d method-to-class relationships..." % len(method_class_rels))
        for i in progress_range(0, len(method_class_rels), batch_size, desc="Method->Class rels"):
            batch = method_class_rels[i : i + batch_size]
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (m:Method {name: rel.method_name, file: rel.method_file, line: rel.method_line}) "
                "MATCH (c:Class {name: rel.class_name, file: rel.method_file}) "
                "MERGE (c)-[:CONTAINS_METHOD]->(m)",
                rels=batch,
            )
    if method_interface_rels:
        logger.info("Creating %d method-to-interface relationships..." % len(method_interface_rels))
        for i in progress_range(
            0, len(method_interface_rels), batch_size, desc="Method->Interface rels"
        ):
            batch = method_interface_rels[i : i + batch_size]
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (m:Method {name: rel.method_name, file: rel.method_file, line: rel.method_line}) "
                "MATCH (i:Interface {name: rel.interface_name, file: rel.method_file}) "
                "MERGE (i)-[:CONTAINS_METHOD]->(m)",
                rels=batch,
            )


def create_method_calls(session: Any, files_data: list[dict[str, Any]]) -> None:
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

            for i in progress_range(
                0, len(filtered_calls), batch_size2, total=total_batches, desc="Other calls"
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
