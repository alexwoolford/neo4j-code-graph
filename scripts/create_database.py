#!/usr/bin/env python3
"""
Create a Neo4j database by name using configured connection settings.

Usage:
  python scripts/create_database.py <database_name> [--uri ... --username ... --password ...]
"""

import argparse
import logging

from neo4j import GraphDatabase

try:
    from src.utils.common import add_common_args, resolve_neo4j_args, setup_logging
except Exception:  # pragma: no cover - repo-local fallback
    from utils.common import add_common_args, resolve_neo4j_args, setup_logging  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Neo4j database by name")
    parser.add_argument("database_name", help="Name of the database to create")
    add_common_args(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging("INFO")
    logger = logging.getLogger(__name__)

    uri, username, password, _ = resolve_neo4j_args(args.uri, args.username, args.password, None)
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        with driver.session() as session:
            try:
                session.run(f"CREATE DATABASE {args.database_name}").consume()  # type: ignore[arg-type]
                logger.info("✅ Created database: %s", args.database_name)
            except Exception as e:
                # If DB already exists or multi-db not supported
                logger.warning("⚠️  Could not create database '%s': %s", args.database_name, e)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
