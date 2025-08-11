#!/usr/bin/env python3
"""
Common utilities shared across neo4j-code-graph scripts.
"""

import argparse
import logging
import sys

from neo4j import Driver, GraphDatabase

from .neo4j_utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()


def setup_logging(log_level: str | int = "INFO", log_file: str | None = None) -> None:
    """Setup logging configuration consistently across scripts.

    Args:
        log_level: Logging level as string ("INFO", "DEBUG") or integer constant
        log_file: Optional path to log file for file output
    """
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    # Handle both string levels ("INFO") and integer levels (logging.INFO)
    if isinstance(log_level, int):
        level = log_level
    else:
        level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )


def create_neo4j_driver(uri: str, username: str, password: str) -> Driver:
    """Create a Neo4j driver with the given connection details.

    Args:
        uri: Neo4j connection URI (bolt:// or neo4j://)
        username: Neo4j username
        password: Neo4j password

    Returns:
        Neo4j driver instance
    """
    uri = ensure_port(uri)
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        driver.verify_connectivity()
    except Exception:
        driver.close()
        raise
    return driver


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add common command-line arguments to an ArgumentParser.

    Args:
        parser: ArgumentParser instance to add arguments to
    """
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument("--username", default=NEO4J_USERNAME, help="Neo4j username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Optional log file")
