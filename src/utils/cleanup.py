#!/usr/bin/env python3
"""
Cleanup script to remove analysis results or perform complete database reset.

Default behavior: Remove SIMILAR relationships and community properties
before re-running similarity and community detection algorithms.

Complete reset: Delete all nodes, relationships, indexes, and constraints
for a fresh start (use --complete flag).
"""

import argparse
import logging
import sys
import time

try:
    from src.utils.common import add_common_args  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from utils.common import add_common_args  # type: ignore

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean up analysis results or perform complete database reset"
    )
    add_common_args(parser)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--complete",
        action="store_true",
        help="Perform complete database reset (deletes ALL nodes and relationships)",
    )
    parser.add_argument(
        "--schema-reset",
        action="store_true",
        help="Drop managed constraints and indexes created by this project",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt for complete reset (use with --complete)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help=(
            "Remove only code-structure data (Files, Methods, Classes, Interfaces, Imports, ExternalDependency)"
        ),
    )
    return parser.parse_args()


from neo4j import Session


def cleanup_similarities(session: Session, dry_run: bool = False) -> int:
    """Remove SIMILAR relationships.

    Returns the number of relationships found before deletion (0 for dry run).
    """
    # Count existing relationships (undirected to be robust)
    result = session.run("MATCH ()-[r:SIMILAR]-() RETURN count(r) as count")
    single = result.single()
    count = int(single["count"]) if single and "count" in single else 0

    if count == 0:
        logger.info("No SIMILAR relationships found")
        return 0

    logger.info("Found %d SIMILAR relationships", count)

    if dry_run:
        logger.info("[DRY RUN] Would delete %d SIMILAR relationships", count)
        return 0

    # Aggressive batched deletion loop using simple LIMIT pattern within a write tx
    batch_size = 50000

    def _batch_delete(tx) -> int:
        rec = tx.run(
            (
                "MATCH ()-[r:SIMILAR]-() "
                "WITH collect(r)[..$limit] AS rels "
                "FOREACH (rel IN rels | DELETE rel) "
                "RETURN size(rels) AS deleted"
            ),
            {"limit": batch_size},
        ).single()
        return int(rec["deleted"]) if rec and "deleted" in rec else 0

    while True:
        deleted = session.execute_write(_batch_delete)
        if deleted == 0:
            break

    logger.info("Deleted SIMILAR relationships")
    return count


def cleanup_communities(
    session: Session, community_property: str = "similarity_community", dry_run: bool = False
) -> None:
    """Remove community properties from Method nodes."""
    # Count nodes with community property (static property name for strict typing)
    result = session.run(
        "MATCH (m:Method) WHERE m.similarity_community IS NOT NULL RETURN count(m) as count"
    )
    single = result.single()
    count = int(single["count"]) if single and "count" in single else 0

    if count == 0:
        logger.info("No nodes found with %s property", community_property)
        return

    logger.info("Found %d Method nodes with %s property", count, community_property)

    if dry_run:
        logger.info(
            "[DRY RUN] Would remove %s property from %d nodes",
            community_property,
            count,
        )
    else:

        def _remove_prop(tx):
            tx.run(
                "MATCH (m:Method) WHERE m.similarity_community IS NOT NULL REMOVE m.similarity_community"
            ).consume()

        session.execute_write(_remove_prop)
        logger.info("Removed %s property from %d Method nodes", community_property, count)


def cleanup_graph_projections(session: Session, dry_run: bool = False) -> None:
    """Remove any lingering GDS graph projections using proper GDS Python client."""
    try:
        from graphdatascience import GraphDataScience

        try:
            from src.utils.common import get_neo4j_config  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            from utils.common import get_neo4j_config  # type: ignore

        # Create GDS client using proper Python client
        uri, username, password, database = get_neo4j_config()
        gds = GraphDataScience(uri, auth=(username, password), database=database)

        # List existing graphs using GDS Python client
        graph_list = gds.graph.list()
        if graph_list.empty:
            logger.info("No GDS graph projections found")
            gds.close()
            return

        graphs = graph_list["graphName"].tolist()
        logger.info("Found GDS graph projections: %s", graphs)

        for graph_name in graphs:
            if dry_run:
                logger.info("[DRY RUN] Would drop graph projection: %s", graph_name)
            else:
                try:
                    gds.run_cypher(
                        "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                        name=graph_name,
                    )
                    logger.info("Dropped graph projection: %s", graph_name)
                except Exception as e:
                    logger.warning("Failed to drop graph %s: %s", graph_name, e)

        gds.close()

    except Exception as e:
        logger.warning("Could not check GDS graph projections: %s", e)


def cleanup_vector_index(session: Session, dry_run: bool = False) -> None:
    """Check vector index status but don't remove it (embeddings are expensive!)."""
    try:
        result = session.run("SHOW VECTOR INDEXES")
        indexes = list(result)

        if indexes:
            logger.info(
                "Found %d vector indexes (keeping them - embeddings are expensive!)",
                len(indexes),
            )
            for record in indexes:
                logger.info(
                    "  - %s on %s",
                    record.get("name", "unnamed"),
                    record.get("labelsOrTypes", ""),
                )
        else:
            logger.info("No vector indexes found")

    except Exception as e:
        logger.warning("Could not check vector indexes: %s", e)


def selective_cleanup(session: Session, dry_run: bool = False) -> None:
    """
    Remove analysis artifacts only (SIMILAR relationships, community properties, GDS graphs).

    This is safe to run before re-computing similarity/community stages and is idempotent.
    """
    logger.info("Starting selective cleanup%s...", " (DRY RUN)" if dry_run else "")
    cleanup_similarities(session, dry_run)
    cleanup_communities(session, "similarity_community", dry_run)
    cleanup_graph_projections(session, dry_run)
    cleanup_vector_index(session, dry_run)
    logger.info("Selective cleanup completed%s", " (DRY RUN)" if dry_run else "")


def complete_database_reset(session: Session, dry_run: bool = False) -> None:
    """Perform complete database reset (delete everything)."""
    # Get initial counts
    result = session.run("MATCH (n) RETURN count(n) as node_count")
    single = result.single()
    initial_nodes = int(single["node_count"]) if single and "node_count" in single else 0

    result = session.run("MATCH ()-[r]->() RETURN count(r) as rel_count")
    single = result.single()
    initial_rels = int(single["rel_count"]) if single and "rel_count" in single else 0

    logger.info("Database contains %d nodes and %d relationships", initial_nodes, initial_rels)

    if initial_nodes == 0 and initial_rels == 0:
        logger.info("Database is already empty")
        return

    if dry_run:
        logger.info(
            "[DRY RUN] Would delete ALL %d nodes and %d relationships",
            initial_nodes,
            initial_rels,
        )
        logger.info("[DRY RUN] Would drop all indexes and constraints")
        return

    logger.info("🗑️  Starting complete database reset...")

    # Safety guard: require explicit env allow flag
    import os as _os

    allow_reset = _os.getenv("CODEGRAPH_ALLOW_RESET", "").lower() in {"1", "true", "yes"}
    if not allow_reset:
        logger.error(
            "Complete reset is disabled. Set CODEGRAPH_ALLOW_RESET=true to enable in this environment."
        )
        return

    # Strategy override: database replacement (Enterprise-only), fastest and most deterministic
    strategy = (_os.getenv("CODEGRAPH_RESET_STRATEGY") or "").lower()
    if strategy in {"replace", "recreate", "create_or_replace"} and not dry_run:
        try:
            db_info = session.run("CALL db.info() YIELD name RETURN name").single()
            current_db = db_info["name"] if db_info and "name" in db_info else None
        except Exception:
            current_db = None
        if current_db:
            try:
                logger.info("⏳ Replacing database '%s' via system command...", current_db)
                session.run(f"USE system CREATE OR REPLACE DATABASE `{current_db}` WAIT").consume()
                # Verify
                verify = session.run(f"USE `{current_db}` MATCH (n) RETURN count(n) AS c").single()
                c = int(verify["c"]) if verify and "c" in verify else -1
                logger.info("✅ Database replaced; node count now: %d", c)
                if c == 0:
                    # Also ensure no relationships
                    rels = session.run(
                        f"USE `{current_db}` MATCH ()-[r]->() RETURN count(r) AS rc"
                    ).single()
                    rc = int(rels["rc"]) if rels and "rc" in rels else -1
                    logger.info("✅ Relationship count now: %d", rc)
                    if rc == 0:
                        return
            except Exception as e:
                logger.warning("Database replace strategy failed, falling back to delete: %s", e)

    # Robust batched DETACH DELETE to remove both relationships and nodes safely
    batch_size = 50000
    total_nodes_deleted = 0

    if initial_nodes > 0 or initial_rels > 0:
        # Prefer APOC periodic iterate when available for scalability
        apoc_ok = False
        try:
            session.run("CALL apoc.help('periodic.iterate')").consume()
            apoc_ok = True
        except Exception:
            apoc_ok = False

        if apoc_ok and not dry_run:
            logger.info("⏳ Using APOC label-wise iterate to wipe database deterministically...")
            try:
                labels_res = session.run("CALL db.labels() YIELD label RETURN label")
                labels = [rec["label"] for rec in labels_res]
            except Exception:
                labels = []
            if labels:
                for lbl in labels:
                    # Skip system/internal labels if present
                    if not lbl or lbl.startswith("_"):
                        continue
                    logger.debug("Deleting label: %s", lbl)
                    cypher = (
                        "CALL apoc.periodic.iterate(\n"
                        f"  'MATCH (n:`{lbl}`) RETURN n',\n"
                        "  'DETACH DELETE n',\n"
                        "  {batchSize:5000, parallel:false}\n"
                        ")"
                    )
                    session.run(cypher).consume()
            else:
                # Fallback to all-nodes iterate
                session.run(
                    "CALL apoc.periodic.iterate(\n"
                    "  'MATCH (n) RETURN n',\n"
                    "  'DETACH DELETE n',\n"
                    "  {batchSize:5000, parallel:false}\n"
                    ")"
                ).consume()
            # Verify
            final = session.run("MATCH (n) RETURN count(n) AS c").single()
            total_nodes_deleted = initial_nodes - int(final["c"]) if final else initial_nodes
            logger.info("✅ Deleted nodes via APOC; remaining: %d", int(final["c"]) if final else 0)
        else:
            logger.info("⏳ Deleting all data in batches of %d (DETACH DELETE)...", batch_size)
            while True:
                result = session.run(
                    (
                        "MATCH (n) "
                        "WITH collect(n)[..$limit] AS nodes "
                        "FOREACH (x IN nodes | DETACH DELETE x) "
                        "RETURN size(nodes) as deleted"
                    ),
                    {"limit": batch_size},
                )
                single = result.single()
                deleted = int(single["deleted"]) if single and "deleted" in single else 0
                if deleted == 0:
                    break
                total_nodes_deleted += deleted
                logger.info("  Deleted %d nodes (total: %d)", deleted, total_nodes_deleted)
                time.sleep(0.05)

            logger.info("✅ Deleted %d nodes (all relationships removed)", total_nodes_deleted)

        # Final sweep: ensure no stragglers remain (e.g., transactional leftovers)
        try:
            session.run("MATCH (n) DETACH DELETE n").consume()
        except Exception:
            pass

    # Drop managed schema if requested via env guard
    try:
        from src.data.schema_management import (
            drop_managed_schema as _drop_schema,  # type: ignore[attr-defined]
        )
    except Exception:
        try:
            from data.schema_management import drop_managed_schema as _drop_schema  # type: ignore
        except Exception:
            _drop_schema = None  # type: ignore

    if _drop_schema is not None and not dry_run:
        logger.info("⏳ Dropping managed schema (constraints/indexes) created by this project...")
        _drop_schema(session)

    # Also drop any vector indexes created for embeddings (discovered dynamically)
    try:
        vidx = session.run("SHOW VECTOR INDEXES")
        for rec in vidx:
            name = rec.get("name")
            if name:
                try:
                    session.run(f"DROP VECTOR INDEX {name} IF EXISTS").consume()
                    logger.info("  ✅ Dropped vector index %s", name)
                except Exception:
                    try:
                        session.run(f"DROP INDEX {name} IF EXISTS").consume()
                        logger.info("  ✅ Dropped index %s", name)
                    except Exception as e2:
                        logger.debug("  ⚠️  Could not drop vector index %s: %s", name, e2)
    except Exception:
        pass

    # Final verification with retry to avoid any transactional visibility edge cases
    attempts = 0
    final_count = -1
    final_rels = -1
    while attempts < 5:
        result = session.run("MATCH (n) RETURN count(n) as final_count")
        single = result.single()
        final_count = int(single["final_count"]) if single and "final_count" in single else 0

        result = session.run("MATCH ()-[r]->() RETURN count(r) as final_rels")
        single = result.single()
        final_rels = int(single["final_rels"]) if single and "final_rels" in single else 0

        if final_count == 0 and final_rels == 0:
            break
        # Best-effort extra sweep if anything remains
        session.run(
            (
                "MATCH (n) "
                "WITH collect(n)[..$limit] AS nodes "
                "FOREACH (x IN nodes | DETACH DELETE x)"
            ),
            {"limit": batch_size},
        ).consume()
        time.sleep(0.05)
        attempts += 1

    logger.info("🎉 COMPLETE RESET FINISHED!")
    logger.info("  Final state: %d nodes, %d relationships", final_count, final_rels)
    if final_count or final_rels:
        try:
            diag = session.run(
                """
                CALL {
                  MATCH (n) RETURN labels(n) AS labels, count(n) AS c
                } RETURN labels, c ORDER BY c DESC LIMIT 10
                """
            )
            rows = list(diag)
            logger.warning("Residual nodes by labels (top 10): %s", rows)
            sample = session.run(
                "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props LIMIT 5"
            )
            logger.warning("Residual node samples: %s", list(sample))
        except Exception:
            pass


def main():
    """Main cleanup function."""
    args = parse_args()

    # Use consistent logging helper
    try:
        from src.utils.common import resolve_neo4j_args, setup_logging  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        from utils.common import resolve_neo4j_args, setup_logging  # type: ignore

    setup_logging(args.log_level, args.log_file)

    try:
        # Use consistent Neo4j connection helper
        try:
            from src.utils.common import create_neo4j_driver  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            from utils.common import create_neo4j_driver  # type: ignore

        _uri, _user, _pwd, _db = resolve_neo4j_args(
            args.uri, args.username, args.password, args.database
        )
        with create_neo4j_driver(_uri, _user, _pwd) as driver:
            logger.info("Connected to Neo4j")

            with driver.session(database=_db) as session:
                if args.complete:
                    # Complete database reset
                    if args.confirm or args.dry_run:
                        response = "RESET"
                    else:
                        response = input(
                            "⚠️  This will DELETE EVERYTHING in the database. "
                            "Type 'RESET' to confirm: "
                        )
                    if response != "RESET":
                        logger.info("Complete reset cancelled.")
                        return

                    logger.info(
                        "Starting complete database reset%s...",
                        " (DRY RUN)" if args.dry_run else "",
                    )
                    complete_database_reset(session, args.dry_run)

                else:
                    if args.fast and not args.complete:
                        logger.info(
                            "Fast cleanup: removing code-structure nodes and relationships%s...",
                            " (DRY RUN)" if args.dry_run else "",
                        )
                        if not args.dry_run:
                            session.run("MATCH (n:Import) DETACH DELETE n").consume()
                            session.run("MATCH (n:ExternalDependency) DETACH DELETE n").consume()
                            session.run("MATCH (n:Method) DETACH DELETE n").consume()
                            session.run("MATCH (n:Interface) DETACH DELETE n").consume()
                            session.run("MATCH (n:Class) DETACH DELETE n").consume()
                            session.run("MATCH (n:File) DETACH DELETE n").consume()
                            session.run("MATCH (n:Directory) DETACH DELETE n").consume()
                        logger.info(
                            "Fast cleanup completed%s", " (DRY RUN)" if args.dry_run else ""
                        )
                        return
                    # Selective cleanup (default behavior)
                    logger.info("Starting cleanup%s...", " (DRY RUN)" if args.dry_run else "")

                    # Clean up similarities
                    cleanup_similarities(session, args.dry_run)

                    # Clean up community properties
                    cleanup_communities(session, "similarity_community", args.dry_run)

                    # Clean up GDS graph projections
                    cleanup_graph_projections(session, args.dry_run)

                    # Check vector indexes (but don't remove)
                    cleanup_vector_index(session, args.dry_run)

                    logger.info("Cleanup completed%s", " (DRY RUN)" if args.dry_run else "")
    except Exception as e:
        logger.error("Failed to connect to Neo4j: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
