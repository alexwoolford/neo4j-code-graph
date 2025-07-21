#!/usr/bin/env python3
"""
Common utilities shared across neo4j-code-graph scripts.
"""

import sys
import logging
import argparse
from neo4j import GraphDatabase
from utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()


def setup_logging(log_level="INFO", log_file=None):
    """Setup logging configuration consistently across scripts."""
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def create_neo4j_driver(uri, username, password):
    """Create and verify Neo4j driver connection."""
    try:
        driver = GraphDatabase.driver(ensure_port(uri), auth=(username, password))
        driver.verify_connectivity()
        logging.getLogger(__name__).info(f"Connected to Neo4j at {ensure_port(uri)}")
        return driver
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to connect to Neo4j: {e}")
        sys.exit(1)


def add_common_args(parser):
    """Add common Neo4j connection arguments to argument parser."""
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument("--username", default=NEO4J_USERNAME, help="Neo4j username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Optional log file")
    return parser


def create_base_parser(description):
    """Create base argument parser with common arguments."""
    parser = argparse.ArgumentParser(description=description)
    return add_common_args(parser)
