#!/usr/bin/env python3
"""
Create a Neo4j database by name using configured connection settings.

Usage:
  python scripts/create_database.py <database_name>
"""

import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: create_database.py <database_name>")
        return 2
    db_name = sys.argv[1]

    from neo4j import GraphDatabase

    from src.utils.neo4j_utils import get_neo4j_config

    uri, username, password, _ = get_neo4j_config()
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        with driver.session() as session:
            try:
                session.run(f"CREATE DATABASE {db_name}").consume()
                print(f"✅ Created database: {db_name}")
            except Exception as e:
                # If DB already exists or multi-db not supported
                print(f"⚠️  Could not create database '{db_name}': {e}")
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
