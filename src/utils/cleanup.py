#!/usr/bin/env python3
"""
Cleanup script to remove analysis results or perform complete database reset.

Default behavior: Remove SIMILAR relationships and community properties
before re-running similarity and community detection algorithms.

Complete reset: Delete all nodes, relationships, indexes, and constraints
for a fresh start (use --complete flag).
"""

import sys
import argparse
import logging
import time
from neo4j import GraphDatabase
from .neo4j_utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean up analysis results or perform complete database reset"
    )
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument("--username", default=NEO4J_USERNAME, help="Neo4j authentication username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j authentication password")
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)")
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
    return parser.parse_args()


def cleanup_similarities(session, dry_run=False):
    """Remove SIMILAR relationships."""
    # Count existing relationships
    result = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) as count")
    count = result.single()["count"]

    if count == 0:
        logger.info("No SIMILAR relationships found")
        return

    logger.info("Found %d SIMILAR relationships", count)

    if dry_run:
        logger.info("[DRY RUN] Would delete %d SIMILAR relationships", count)
    else:
        session.run("MATCH ()-[r:SIMILAR]->() DELETE r")
        logger.info("Deleted %d SIMILAR relationships", count)


def cleanup_communities(session, community_property="similarityCommunity", dry_run=False):
    """Remove community properties from Method nodes."""
    # Count nodes with community property
    result = session.run(
        f"MATCH (m:Method) WHERE m.{community_property} IS NOT NULL RETURN count(m) as count"
    )
    count = result.single()["count"]

    if count == 0:
        logger.info("No nodes found with %s property", community_property)
        return

    logger.info("Found %d Method nodes with %s property", count, community_property)

    if dry_run:
        logger.info("[DRY RUN] Would remove %s property from %d nodes", community_property, count)
    else:
        session.run(
            f"MATCH (m:Method) WHERE m.{community_property} IS NOT NULL "
            f"REMOVE m.{community_property}"
        )
        logger.info("Removed %s property from %d Method nodes", community_property, count)


def cleanup_graph_projections(session, dry_run=False):
    """Remove any lingering GDS graph projections."""
    # This requires the graphdatascience package, but we'll do it via Cypher
    try:
        # List existing graphs
        result = session.run("CALL gds.graph.list() YIELD graphName")
        graphs = [record["graphName"] for record in result]

        if not graphs:
            logger.info("No GDS graph projections found")
            return

        logger.info("Found GDS graph projections: %s", graphs)

        for graph_name in graphs:
            if dry_run:
                logger.info("[DRY RUN] Would drop graph projection: %s", graph_name)
            else:
                try:
                    session.run("CALL gds.graph.drop($graphName)", graphName=graph_name)
                    logger.info("Dropped graph projection: %s", graph_name)
                except Exception as e:
                    logger.warning("Failed to drop graph %s: %s", graph_name, e)

    except Exception as e:
        logger.warning("Could not check GDS graph projections: %s", e)


def cleanup_vector_index(session, dry_run=False):
    """Check vector index status but don't remove it (embeddings are expensive!)."""
    try:
        result = session.run("SHOW VECTOR INDEXES")
        indexes = list(result)

        if indexes:
            logger.info(
                "Found %d vector indexes (keeping them - embeddings are expensive!)", len(indexes)
            )
            for record in indexes:
                logger.info(
                    "  - %s on %s", record.get("name", "unnamed"), record.get("labelsOrTypes", "")
                )
        else:
            logger.info("No vector indexes found")

    except Exception as e:
        logger.warning("Could not check vector indexes: %s", e)


def complete_database_reset(session, dry_run=False):
    """Perform complete database reset (delete everything)."""
    # Get initial counts
    result = session.run("MATCH (n) RETURN count(n) as node_count")
    initial_nodes = result.single()["node_count"]

    result = session.run("MATCH ()-[r]->() RETURN count(r) as rel_count")
    initial_rels = result.single()["rel_count"]

    logger.info("Database contains %d nodes and %d relationships", initial_nodes, initial_rels)

    if initial_nodes == 0 and initial_rels == 0:
        logger.info("Database is already empty")
        return

    if dry_run:
        logger.info(
            "[DRY RUN] Would delete ALL %d nodes and %d relationships", initial_nodes, initial_rels
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
                f"MATCH ()-[r]->() WITH r LIMIT {batch_size} DELETE r RETURN count(*) as deleted"
            )
            deleted = result.single()["deleted"]
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
                f"MATCH (n) WITH n LIMIT {batch_size} DELETE n RETURN count(*) as deleted"
            )
            deleted = result.single()["deleted"]
            if deleted == 0:
                break
            total_nodes_deleted += deleted
            logger.info("  Deleted %d nodes (total: %d)", deleted, total_nodes_deleted)
            time.sleep(0.1)

        logger.info("✅ Deleted %d nodes", total_nodes_deleted)

    # Drop indexes and constraints
    logger.info("⏳ Dropping indexes and constraints...")
    cleanup_queries = [
        "DROP CONSTRAINT commit_sha IF EXISTS",
        "DROP CONSTRAINT developer_email IF EXISTS",
        "DROP INDEX file_path_index IF EXISTS",
        "DROP INDEX file_ver_composite IF EXISTS",
    ]

    for query in cleanup_queries:
        try:
            session.run(query)
            logger.info("  ✅ %s", query)
        except Exception as e:
            logger.warning("  ⚠️  %s: %s", query, e)

    # Try to drop vector index (may not exist or may have different syntax)
    try:
        # Try newer syntax first
        session.run("DROP VECTOR INDEX method_embeddings IF EXISTS")
        logger.info("  ✅ Dropped vector index method_embeddings")
    except Exception as e:
        try:
            # Try alternative syntax
            session.run("DROP INDEX method_embeddings IF EXISTS")
            logger.info("  ✅ Dropped index method_embeddings")
        except Exception as e:
            logger.warning("  ⚠️  Could not drop vector index: %s", e)

    # Final verification
    result = session.run("MATCH (n) RETURN count(n) as final_count")
    final_count = result.single()["final_count"]

    result = session.run("MATCH ()-[r]->() RETURN count(r) as final_rels")
    final_rels = result.single()["final_rels"]

    logger.info("🎉 COMPLETE RESET FINISHED!")
    logger.info("  Final state: %d nodes, %d relationships", final_count, final_rels)


def main():
    """Main cleanup function."""
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    try:
        driver = GraphDatabase.driver(ensure_port(args.uri), auth=(args.username, args.password))
        driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", ensure_port(args.uri))
    except Exception as e:
        logger.error("Failed to connect to Neo4j: %s", e)
        sys.exit(1)

    try:
        with driver.session(database=args.database) as session:
            if args.complete:
                # Complete database reset
                if not args.confirm and not args.dry_run:
                    response = input(
                        "⚠️  This will DELETE EVERYTHING in the database. Type 'RESET' to confirm: "
                    )
                    if response != "RESET":
                        logger.info("Complete reset cancelled.")
                        return

                logger.info(
                    "Starting complete database reset%s...", " (DRY RUN)" if args.dry_run else ""
                )
                complete_database_reset(session, args.dry_run)

            else:
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

    finally:
        driver.close()


if __name__ == "__main__":
    main()
