#!/usr/bin/env python3
"""
Cleanup script to remove SIMILAR relationships and community properties
before re-running similarity and community detection algorithms.
"""

import sys
import argparse
import logging
from neo4j import GraphDatabase
from utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean up SIMILAR relationships and community properties"
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
            f"MATCH (m:Method) WHERE m.{community_property} IS NOT NULL REMOVE m.{community_property}"
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
