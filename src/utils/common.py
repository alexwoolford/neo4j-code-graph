#!/usr/bin/env python3
"""
Common utilities shared across neo4j-code-graph scripts.
"""

import sys
import logging
import argparse
from neo4j import GraphDatabase
from .neo4j_utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()


def setup_logging(log_level="INFO", log_file=None):
    """Setup logging configuration consistently across scripts."""
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
    )


def create_neo4j_driver(uri, username, password):
    """Create a Neo4j driver with the given connection details."""
    uri = ensure_port(uri)
    return GraphDatabase.driver(uri, auth=(username, password))


def add_common_args(parser):
    """Add common command-line arguments to an ArgumentParser."""
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument("--username", default=NEO4J_USERNAME, help="Neo4j username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Optional log file")
