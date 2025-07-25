#!/usr/bin/env python3
"""
Schema Management for neo4j-code-graph

Centralizes the creation of constraints and indexes for all node types
based on their natural keys. This ensures data integrity and performance.
"""

import logging

logger = logging.getLogger(__name__)


def create_schema_constraints_and_indexes(session):
    """
    Create all necessary unique constraints and indexes for natural keys.

    This should be called before any data loading to ensure:
    1. Data integrity through unique constraints
    2. Performance optimization through indexes
    3. Prevention of duplicate nodes/relationships
    """

    logger.info("Creating schema constraints and indexes...")

    # =============================================================================
    # UNIQUE CONSTRAINTS (enforce natural key uniqueness)
    # =============================================================================

    constraints = [
        # Directory: unique by path
        (
            "directory_path",
            "Directory",
            "path",
            "CREATE CONSTRAINT directory_path IF NOT EXISTS "
            "FOR (d:Directory) REQUIRE d.path IS UNIQUE",
        ),
        # File: unique by path - allows same filename in different directories
        (
            "file_path",
            "File",
            "path",
            "CREATE CONSTRAINT file_path IF NOT EXISTS " "FOR (f:File) REQUIRE f.path IS UNIQUE",
        ),
        # Class: unique by (name, file) - same class name can exist in different files
        (
            "class_name_file",
            "Class",
            "(name, file)",
            "CREATE CONSTRAINT class_name_file IF NOT EXISTS "
            "FOR (c:Class) REQUIRE (c.name, c.file) IS UNIQUE",
        ),
        # Interface: unique by (name, file) - same interface name can exist in different files
        (
            "interface_name_file",
            "Interface",
            "(name, file)",
            "CREATE CONSTRAINT interface_name_file IF NOT EXISTS "
            "FOR (i:Interface) REQUIRE (i.name, i.file) IS UNIQUE",
        ),
        # Method: unique by (name, file, line) - allows method overloading but
        # ensures unique signatures
        (
            "method_name_file_line",
            "Method",
            "(name, file, line)",
            "CREATE CONSTRAINT method_name_file_line IF NOT EXISTS "
            "FOR (m:Method) REQUIRE (m.name, m.file, m.line) IS UNIQUE",
        ),
        # Git history constraints
        (
            "commit_sha",
            "Commit",
            "sha",
            "CREATE CONSTRAINT commit_sha IF NOT EXISTS " "FOR (c:Commit) REQUIRE c.sha IS UNIQUE",
        ),
        # Developer: unique by email
        (
            "developer_email",
            "Developer",
            "email",
            "CREATE CONSTRAINT developer_email IF NOT EXISTS "
            "FOR (d:Developer) REQUIRE d.email IS UNIQUE",
        ),
        # FileVer: unique by (sha, path) - same file can exist in multiple commits
        (
            "file_ver_sha_path",
            "FileVer",
            "(sha, path)",
            "CREATE CONSTRAINT file_ver_sha_path IF NOT EXISTS "
            "FOR (fv:FileVer) REQUIRE (fv.sha, fv.path) IS UNIQUE",
        ),
        # External dependencies
        (
            "external_dependency_path",
            "ExternalDependency",
            "import_path",
            "CREATE CONSTRAINT external_dependency_path IF NOT EXISTS "
            "FOR (ed:ExternalDependency) REQUIRE ed.import_path IS UNIQUE",
        ),
        # Import: unique by import_path
        (
            "import_path",
            "Import",
            "import_path",
            "CREATE CONSTRAINT import_path IF NOT EXISTS "
            "FOR (i:Import) REQUIRE i.import_path IS UNIQUE",
        ),
        # CVE: unique by CVE ID
        (
            "cve_id",
            "CVE",
            "cve_id",
            "CREATE CONSTRAINT cve_id IF NOT EXISTS " "FOR (cve:CVE) REQUIRE cve.cve_id IS UNIQUE",
        ),
    ]

    for constraint_name, node_type, key_desc, cypher in constraints:
        try:
            session.run(cypher)
            logger.info(f"✅ Created constraint {constraint_name}: {node_type}({key_desc})")
        except Exception as e:
            if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                logger.debug(f"  ⚠️  Constraint {constraint_name} already exists")
            else:
                logger.warning(f"  ❌ Failed to create constraint {constraint_name}: {e}")

    # =============================================================================
    # PERFORMANCE INDEXES (for commonly queried properties)
    # =============================================================================

    indexes = [
        # Performance indexes for code analysis
        (
            "class_estimated_lines",
            "Class",
            "CREATE INDEX class_estimated_lines IF NOT EXISTS "
            "FOR (c:Class) ON (c.estimated_lines)",
        ),
        (
            "interface_method_count",
            "Interface",
            "CREATE INDEX interface_method_count IF NOT EXISTS "
            "FOR (i:Interface) ON (i.method_count)",
        ),
        # Method performance indexes
        (
            "method_estimated_lines",
            "Method",
            "CREATE INDEX method_estimated_lines IF NOT EXISTS "
            "FOR (m:Method) ON (m.estimated_lines)",
        ),
        (
            "method_is_public",
            "Method",
            "CREATE INDEX method_is_public IF NOT EXISTS FOR (m:Method) ON (m.is_public)",
        ),
        (
            "method_is_static",
            "Method",
            "CREATE INDEX method_is_static IF NOT EXISTS FOR (m:Method) ON (m.is_static)",
        ),
        (
            "method_is_abstract",
            "Method",
            "CREATE INDEX method_is_abstract IF NOT EXISTS FOR (m:Method) ON (m.is_abstract)",
        ),
        # Git history indexes
        (
            "commit_date",
            "Commit",
            "CREATE INDEX commit_date IF NOT EXISTS FOR (c:Commit) ON (c.date)",
        ),
        # Centrality indexes
        (
            "method_pagerank",
            "Method",
            "CREATE INDEX method_pagerank IF NOT EXISTS " "FOR (m:Method) ON (m.pagerank_score)",
        ),
        (
            "method_betweenness",
            "Method",
            "CREATE INDEX method_betweenness IF NOT EXISTS "
            "FOR (m:Method) ON (m.betweenness_score)",
        ),
        # Community detection indexes
        (
            "method_similarity_community",
            "Method",
            "CREATE INDEX method_similarity_community IF NOT EXISTS "
            "FOR (m:Method) ON (m.similarityCommunity)",
        ),
    ]

    for index_name, node_type, cypher in indexes:
        try:
            session.run(cypher)
            logger.info(f"✅ Created index {index_name} on {node_type}")
        except Exception as e:
            if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                logger.debug(f"  ⚠️  Index {index_name} already exists")
            else:
                logger.warning(f"  ❌ Failed to create index {index_name}: {e}")

    logger.info("Schema setup completed")


def verify_schema_constraints(session):
    """
    Verify that all expected constraints exist in the database.
    Returns a report of existing constraints.
    """

    logger.info("Verifying schema constraints...")

    # Get all constraints
    result = session.run("SHOW CONSTRAINTS")
    existing_constraints = []

    for record in result:
        constraint_info = {
            "name": record.get("name", "Unknown"),
            "type": record.get("type", "Unknown"),
            "entityType": record.get("entityType", "Unknown"),
            "labelsOrTypes": record.get("labelsOrTypes", []),
            "properties": record.get("properties", []),
        }
        existing_constraints.append(constraint_info)

    logger.info(f"Found {len(existing_constraints)} existing constraints:")
    for constraint in existing_constraints:
        labels = ",".join(constraint["labelsOrTypes"]) if constraint["labelsOrTypes"] else "N/A"
        props = ",".join(constraint["properties"]) if constraint["properties"] else "N/A"
        logger.info(f"  • {constraint['name']}: {constraint['type']} on {labels}({props})")

    return existing_constraints


def verify_schema_indexes(session):
    """
    Verify that all expected indexes exist in the database.
    Returns a report of existing indexes.
    """

    logger.info("Verifying schema indexes...")

    # Get all indexes
    result = session.run("SHOW INDEXES")
    existing_indexes = []

    for record in result:
        index_info = {
            "name": record.get("name", "Unknown"),
            "type": record.get("type", "Unknown"),
            "entityType": record.get("entityType", "Unknown"),
            "labelsOrTypes": record.get("labelsOrTypes", []),
            "properties": record.get("properties", []),
            "state": record.get("state", "Unknown"),
        }
        existing_indexes.append(index_info)

    logger.info(f"Found {len(existing_indexes)} existing indexes:")
    for index in existing_indexes:
        labels = ",".join(index["labelsOrTypes"]) if index["labelsOrTypes"] else "N/A"
        props = ",".join(index["properties"]) if index["properties"] else "N/A"
        logger.info(f"  • {index['name']}: {index['type']} on {labels}({props}) - {index['state']}")

    return existing_indexes


def setup_complete_schema(session):
    """
    Complete schema setup: constraints + indexes + verification.
    This is the main function to call for schema management.
    """

    logger.info("🏗️  Setting up complete database schema...")

    # Create constraints and indexes
    create_schema_constraints_and_indexes(session)

    # Verify everything was created
    constraints = verify_schema_constraints(session)
    indexes = verify_schema_indexes(session)

    logger.info(f"✅ Schema setup complete: {len(constraints)} constraints, {len(indexes)} indexes")

    return {"constraints": constraints, "indexes": indexes}


def main():
    """
    Main entry point for schema management CLI.
    """
    import argparse
    import sys
    from pathlib import Path

    # Add src to path for imports when called from CLI wrapper
    root_dir = Path(__file__).parent.parent.parent
    if str(root_dir / "src") not in sys.path:
        sys.path.insert(0, str(root_dir / "src"))

    try:
        from utils.common import add_common_args, create_neo4j_driver, setup_logging
    except ImportError:
        # Fallback for relative imports when used as module
        from ..utils.common import add_common_args, create_neo4j_driver, setup_logging

    parser = argparse.ArgumentParser(description="Setup database schema constraints and indexes")
    add_common_args(parser)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing schema, don't create new constraints/indexes",
    )

    args = parser.parse_args()
    setup_logging(args.log_level, args.log_file)

    driver = create_neo4j_driver(args.uri, args.username, args.password)

    try:
        with driver.session(database=args.database) as session:
            if args.verify_only:
                verify_schema_constraints(session)
                verify_schema_indexes(session)
            else:
                setup_complete_schema(session)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
