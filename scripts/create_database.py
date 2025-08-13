#!/usr/bin/env python3
"""
Create a Neo4j database by name using configured connection settings.

Usage:
  python scripts/create_database.py <database_name>
"""

import logging
import sys


def main() -> int:
    if len(sys.argv) < 2:
        from src.utils.common import setup_logging

        setup_logging("INFO")
        logging.getLogger(__name__).error("Usage: create_database.py <database_name>")
        return 2
    db_name = sys.argv[1]

    from neo4j import GraphDatabase

    from src.utils.common import setup_logging
    from src.utils.neo4j_utils import get_neo4j_config

    setup_logging("INFO")
    logger = logging.getLogger(__name__)

    uri, username, password, _ = get_neo4j_config()
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        with driver.session() as session:
            try:
                session.run(f"CREATE DATABASE {db_name}").consume()
                logger.info("✅ Created database: %s", db_name)
            except Exception as e:
                # If DB already exists or multi-db not supported
                logger.warning("⚠️  Could not create database '%s': %s", db_name, e)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
