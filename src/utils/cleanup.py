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

from .common import add_common_args

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


def cleanup_similarities(session: Session, dry_run: bool = False) -> None:
    """Remove SIMILAR relationships."""
    # Count existing relationships
    result = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) as count")
    single = result.single()
    count = int(single["count"]) if single and "count" in single else 0

    if count == 0:
        logger.info("No SIMILAR relationships found")
        return

    logger.info("Found %d SIMILAR relationships", count)

    if dry_run:
        logger.info("[DRY RUN] Would delete %d SIMILAR relationships", count)
    else:
        session.run("MATCH ()-[r:SIMILAR]->() DELETE r")
        logger.info("Deleted %d SIMILAR relationships", count)


def cleanup_communities(
    session: Session, community_property: str = "similarityCommunity", dry_run: bool = False
) -> None:
    """Remove community properties from Method nodes."""
    # Count nodes with community property (static property name for strict typing)
    result = session.run(
        "MATCH (m:Method) WHERE m.similarityCommunity IS NOT NULL RETURN count(m) as count"
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
        session.run(
            "MATCH (m:Method) WHERE m.similarityCommunity IS NOT NULL REMOVE m.similarityCommunity"
        )
        logger.info("Removed %s property from %d Method nodes", community_property, count)


def cleanup_graph_projections(session: Session, dry_run: bool = False) -> None:
    """Remove any lingering GDS graph projections using proper GDS Python client."""
    try:
        from graphdatascience import GraphDataScience

        from .common import get_neo4j_config

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
                    gds.graph.drop(graph_name)
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

    # Delete relationships in batches to avoid memory issues
    batch_size = 50000
    total_rel_deleted = 0

    if initial_rels > 0:
        logger.info("⏳ Deleting relationships in batches of %d...", batch_size)
        while True:
            result = session.run(
                "MATCH ()-[r]->() WITH r LIMIT $limit DELETE r RETURN count(*) as deleted",
                {"limit": batch_size},
            )
            single = result.single()
            deleted = int(single["deleted"]) if single and "deleted" in single else 0
            if deleted == 0:
                break
            total_rel_deleted += deleted
            logger.info("  Deleted %d relationships (total: %d)", deleted, total_rel_deleted)
            time.sleep(0.1)  # Brief pause to avoid overwhelming the server

        logger.info("✅ Deleted %d relationships", total_rel_deleted)

    # Delete nodes in batches
    total_nodes_deleted = 0

    if initial_nodes > 0:
        logger.info("⏳ Deleting nodes in batches of %d...", batch_size)
        while True:
            result = session.run(
                "MATCH (n) WITH n LIMIT $limit DELETE n RETURN count(*) as deleted",
                {"limit": batch_size},
            )
            single = result.single()
            deleted = int(single["deleted"]) if single and "deleted" in single else 0
            if deleted == 0:
                break
            total_nodes_deleted += deleted
            logger.info("  Deleted %d nodes (total: %d)", deleted, total_nodes_deleted)
            time.sleep(0.1)

        logger.info("✅ Deleted %d nodes", total_nodes_deleted)

    # Drop indexes and constraints
    logger.info("⏳ Dropping indexes and constraints...")
    # Drop a few known constraints/indexes using literal strings to satisfy strict typing
    try:
        session.run("DROP CONSTRAINT commit_sha IF EXISTS")
        logger.info("  ✅ DROP CONSTRAINT commit_sha IF EXISTS")
    except Exception as e:
        logger.warning("  ⚠️  DROP CONSTRAINT commit_sha IF EXISTS: %s", e)
    try:
        session.run("DROP CONSTRAINT developer_email IF EXISTS")
        logger.info("  ✅ DROP CONSTRAINT developer_email IF EXISTS")
    except Exception as e:
        logger.warning("  ⚠️  DROP CONSTRAINT developer_email IF EXISTS: %s", e)
    try:
        session.run("DROP INDEX file_path_index IF EXISTS")
        logger.info("  ✅ DROP INDEX file_path_index IF EXISTS")
    except Exception as e:
        logger.warning("  ⚠️  DROP INDEX file_path_index IF EXISTS: %s", e)
    try:
        session.run("DROP INDEX file_ver_composite IF EXISTS")
        logger.info("  ✅ DROP INDEX file_ver_composite IF EXISTS")
    except Exception as e:
        logger.warning("  ⚠️  DROP INDEX file_ver_composite IF EXISTS: %s", e)

    # Try to drop vector index (may not exist or may have different syntax)
    try:
        # Try newer syntax first
        session.run("DROP VECTOR INDEX method_embeddings IF EXISTS")
        logger.info("  ✅ Dropped vector index method_embeddings")
    except Exception:
        try:
            # Try alternative syntax
            session.run("DROP INDEX method_embeddings IF EXISTS")
            logger.info("  ✅ Dropped index method_embeddings")
        except Exception as e:
            logger.warning("  ⚠️  Could not drop vector index: %s", e)

    # Final verification
    result = session.run("MATCH (n) RETURN count(n) as final_count")
    single = result.single()
    final_count = int(single["final_count"]) if single and "final_count" in single else 0

    result = session.run("MATCH ()-[r]->() RETURN count(r) as final_rels")
    single = result.single()
    final_rels = int(single["final_rels"]) if single and "final_rels" in single else 0

    logger.info("🎉 COMPLETE RESET FINISHED!")
    logger.info("  Final state: %d nodes, %d relationships", final_count, final_rels)


def main():
    """Main cleanup function."""
    args = parse_args()

    # Use consistent logging helper
    from .common import setup_logging

    setup_logging(args.log_level, args.log_file)

    try:
        # Use consistent Neo4j connection helper
        from .common import create_neo4j_driver

        with create_neo4j_driver(args.uri, args.username, args.password) as driver:
            logger.info("Connected to Neo4j at %s", args.uri)

            with driver.session(database=args.database) as session:
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
                    cleanup_communities(session, "similarityCommunity", args.dry_run)

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
