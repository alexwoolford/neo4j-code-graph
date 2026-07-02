#!/usr/bin/env python3
"""Stale-footprint reconcile for incremental ingest (WP4 Phase 4).

The correctness heart of incremental ingest. A naive ``DETACH DELETE`` of a
changed file's Methods would destroy the *incoming* ``:CALLS`` edges from
*unchanged* files — edges a subset re-write never recreates — so the incremental
graph would diverge from a fresh full ingest. Therefore we **reconcile, not
raze**:

1. Delete nodes that *disappeared* from the file (renamed/removed methods,
   classes, interfaces, fields). ``DETACH DELETE`` here is correct: their
   incoming edges (CALLS to a deleted method, EXTENDS to a removed class)
   *should* die, exactly as a full ingest of HEAD would omit them.
2. For *surviving* nodes, delete only the OUTGOING relationships this file's
   parse is responsible for (CALLS/CREATES/THROWS/ANNOTATED/CALLS_EXTERNAL from
   methods, EXTENDS/IMPLEMENTS/ANNOTATED/NESTED_IN from types, ANNOTATED from
   fields, OF_TYPE from parameters, IMPORTS from the file). Incoming edges from
   unchanged callers stay valid because the node itself survives.
3. Re-run the normal MERGE writers over the subset ``files_data`` (they are
   subset-safe), then garbage-collect orphaned :Import nodes and their
   :DEPENDS_ON edges.

Doc nodes are per-file (their id hashes the file path) and belong to exactly one
file, so they are simply deleted and rebuilt.

Known soundness exception
-------------------------
``create_method_calls`` (and ``OF_TYPE`` / ``CREATES`` linking) fall back to
*globally-unique simple names* when an exact resolution is unavailable. Because
those fallbacks depend on the whole-graph name distribution, an incremental
patch can keep (or omit) a fallback edge that a fresh full ingest would resolve
differently once the global name set shifts (e.g. a name that was unique becomes
ambiguous after another file is added). This is within the project's stated
soundness ceiling — CALLS is a ranked triage signal, not proof — and callers
that need exact parity should force a full re-ingest.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

logger = logging.getLogger(__name__)

try:
    _writer = import_module("src.data.graph_writer")
except Exception:  # pragma: no cover
    _writer = import_module("data.graph_writer")
bulk_create_nodes_and_relationships = _writer.bulk_create_nodes_and_relationships


def _footprint_sets(file_data: dict[str, Any]) -> dict[str, Any]:
    """Compute the new natural-key sets for a freshly parsed file."""
    methods = file_data.get("methods", []) or []
    new_sigs = [m.get("method_signature") for m in methods if m.get("method_signature")]
    new_classes = [c.get("name") for c in file_data.get("classes", []) or [] if c.get("name")]
    new_interfaces = [i.get("name") for i in file_data.get("interfaces", []) or [] if i.get("name")]
    new_fields = [
        [f.get("owner_name"), f.get("name")]
        for f in file_data.get("fields", []) or []
        if f.get("owner_name") and f.get("name")
    ]
    return {
        "sigs": new_sigs,
        "classes": new_classes,
        "interfaces": new_interfaces,
        "fields": new_fields,
    }


def _reconcile_file(
    session: Any,
    path: str,
    sigs: list[Any],
    classes: list[Any],
    interfaces: list[Any],
    fields: list[Any],
) -> None:
    """Delete the stale footprint of one file, preserving incoming edges.

    Empty ``sigs``/``classes``/``interfaces``/``fields`` (a deleted file) makes
    every method/class/interface/field of the file "disappeared", removing the
    whole structural footprint while keeping the :File node itself.
    """
    # 1. Methods that disappeared (renamed/removed): full detach + their params.
    #    Their incoming CALLS SHOULD die, matching a fresh full ingest.
    session.run(
        """
        MATCH (m:Method {file: $path})
        WHERE NOT m.method_signature IN $sigs
        OPTIONAL MATCH (m)-[:HAS_PARAMETER]->(prm:Parameter)
        DETACH DELETE prm, m
        """,
        path=path,
        sigs=sigs,
    )

    # 2. Fields that disappeared (keyed by owner_name+name within the file).
    session.run(
        """
        MATCH (fld:Field {file: $path})
        WHERE NOT [fld.owner_name, fld.name] IN $fields
        DETACH DELETE fld
        """,
        path=path,
        fields=fields,
    )

    # 3. Classes / interfaces that disappeared. Incoming EXTENDS/IMPLEMENTS from
    #    other files correctly die with them.
    session.run(
        """
        MATCH (c:Class {file: $path})
        WHERE NOT c.name IN $classes
        DETACH DELETE c
        """,
        path=path,
        classes=classes,
    )
    session.run(
        """
        MATCH (i:Interface {file: $path})
        WHERE NOT i.name IN $interfaces
        DETACH DELETE i
        """,
        path=path,
        interfaces=interfaces,
    )

    # 4. Docs are per-file (id hashes the path). Delete + rebuild is exact.
    session.run("MATCH (d:Doc {file: $path}) DETACH DELETE d", path=path)

    # 5. Surviving methods: drop rebuilt outgoing edges (incoming preserved).
    session.run(
        """
        MATCH (m:Method {file: $path})
        OPTIONAL MATCH (m)-[r:CALLS|CREATES|THROWS|ANNOTATED|CALLS_EXTERNAL]->()
        DELETE r
        """,
        path=path,
    )

    # 6. Surviving parameters: drop rebuilt OF_TYPE edges.
    session.run(
        """
        MATCH (m:Method {file: $path})-[:HAS_PARAMETER]->(prm:Parameter)
        OPTIONAL MATCH (prm)-[r:OF_TYPE]->()
        DELETE r
        """,
        path=path,
    )

    # 7. Surviving classes: drop rebuilt outgoing structural edges.
    session.run(
        """
        MATCH (c:Class {file: $path})
        OPTIONAL MATCH (c)-[r:EXTENDS|IMPLEMENTS|ANNOTATED|NESTED_IN]->()
        DELETE r
        """,
        path=path,
    )

    # 8. Surviving interfaces: drop rebuilt outgoing structural edges.
    session.run(
        """
        MATCH (i:Interface {file: $path})
        OPTIONAL MATCH (i)-[r:EXTENDS|ANNOTATED|NESTED_IN]->()
        DELETE r
        """,
        path=path,
    )

    # 9. Surviving fields: drop rebuilt outgoing ANNOTATED edges.
    session.run(
        """
        MATCH (fld:Field {file: $path})
        OPTIONAL MATCH (fld)-[r:ANNOTATED]->()
        DELETE r
        """,
        path=path,
    )

    # 10. File-level IMPORTS edges (Import nodes are shared, so relationship-only).
    session.run(
        "MATCH (f:File {path: $path})-[r:IMPORTS]->(:Import) DELETE r",
        path=path,
    )


def _gc_orphan_imports(session: Any) -> int:
    """Delete :Import nodes no longer referenced by any :IMPORTS edge.

    DETACH DELETE also removes their outbound :DEPENDS_ON edges. Returns the
    number of Import nodes removed.
    """
    rec = session.run(
        """
        MATCH (i:Import)
        WHERE NOT ()-[:IMPORTS]->(i)
        WITH collect(i) AS orphans
        FOREACH (i IN orphans | DETACH DELETE i)
        RETURN size(orphans) AS removed
        """
    ).single()
    removed = int(rec["removed"]) if rec else 0
    if removed:
        logger.info("Garbage-collected %d orphan Import nodes", removed)
    return removed


def patch_changed_files(
    session: Any,
    repo_path: str,
    files_data: list[dict[str, Any]],
    changed: list[str],
    deleted_paths: list[str],
    dependency_versions: dict[str, str] | None = None,
) -> None:
    """Patch the graph for a HEAD delta: reconcile footprints then subset-write.

    Args:
        session: open Neo4j session.
        repo_path: repository root (unused by the DB writes; kept for parity and
            future path resolution).
        files_data: freshly-parsed data for the changed/added files ONLY.
        changed: repo-relative paths of added/modified files (present in
            ``files_data``).
        deleted_paths: repo-relative paths of files removed at HEAD.
        dependency_versions: resolved dependency versions for import linking.

    See the module docstring for the documented globally-unique-name CALLS
    fallback soundness exception.
    """
    files_by_path: dict[str, dict[str, Any]] = {}
    for fd in files_data:
        p = fd.get("path")
        if isinstance(p, str):
            files_by_path[p] = fd

    # 1. Reconcile changed/added files against their fresh footprint sets.
    for path in changed:
        fd = files_by_path.get(path)
        if fd is None:
            # File is in the delta but produced no parse (e.g. parse error /
            # skipped). Reconcile with empty sets is too aggressive; skip so we
            # never silently wipe a file whose new parse we don't have.
            logger.warning("Changed file %s has no extracted data; skipping reconcile", path)
            continue
        sets = _footprint_sets(fd)
        _reconcile_file(
            session,
            path,
            sets["sigs"],
            sets["classes"],
            sets["interfaces"],
            sets["fields"],
        )

    # 2. Reconcile deleted files with empty sets (remove entire footprint) but
    #    KEEP the :File node — it anchors git history (FileVer-[:OF_FILE]->File)
    #    and CO_CHANGED. Flag it and clear structure props.
    for path in deleted_paths:
        _reconcile_file(session, path, [], [], [], [])
        # Drop the Directory-[:CONTAINS]->File edge: the file is no longer in the
        # source tree, so a fresh full ingest of HEAD (where the :File node is
        # created only by git history) has no such structural edge.
        session.run(
            "MATCH (:Directory)-[r:CONTAINS]->(:File {path: $path}) DELETE r",
            path=path,
        )
        session.run(
            """
            MATCH (f:File {path: $path})
            SET f.deleted_at_head = true
            REMOVE f.method_count, f.class_count, f.interface_count,
                   f.total_lines, f.code_lines
            """,
            path=path,
        )

    # 3. Re-run the normal MERGE writers over the subset. Subset-safe: every
    #    writer keys on natural ids and MERGEs. The global DEPENDS_ON join and
    #    fail-fast validation inside create_imports run over ALL imports (both
    #    idempotent), so unchanged files stay linked.
    if files_data:
        bulk_create_nodes_and_relationships(
            session, files_data, dependency_versions=dependency_versions
        )

    # 4. GC orphaned Import nodes (an import removed from the last file that used
    #    it) plus their DEPENDS_ON edges.
    _gc_orphan_imports(session)
