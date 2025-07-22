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
        ("directory_path", "Directory", "path",
         "CREATE CONSTRAINT directory_path IF NOT EXISTS FOR (d:Directory) REQUIRE d.path IS UNIQUE"),

        # File: unique by path
        ("file_path", "File", "path",
         "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE"),

        # Class: unique by (name, file) - same class name can exist in different files
        ("class_name_file", "Class", "(name, file)",
         "CREATE CONSTRAINT class_name_file IF NOT EXISTS FOR (c:Class) REQUIRE (c.name, c.file) IS UNIQUE"),

        # Interface: unique by (name, file) - same interface name can exist in different files
        ("interface_name_file", "Interface", "(name, file)",
         "CREATE CONSTRAINT interface_name_file IF NOT EXISTS FOR (i:Interface) REQUIRE (i.name, i.file) IS UNIQUE"),

        # Method: unique by (name, file, line) - allows method overloading but ensures unique signatures
        ("method_name_file_line", "Method", "(name, file, line)",
         "CREATE CONSTRAINT method_name_file_line IF NOT EXISTS FOR (m:Method) REQUIRE (m.name, m.file, m.line) IS UNIQUE"),

        # Commit: unique by sha
        ("commit_sha", "Commit", "sha",
         "CREATE CONSTRAINT commit_sha IF NOT EXISTS FOR (c:Commit) REQUIRE c.sha IS UNIQUE"),

        # Developer: unique by email (names can be duplicated, emails should be unique)
        ("developer_email", "Developer", "email",
         "CREATE CONSTRAINT developer_email IF NOT EXISTS FOR (d:Developer) REQUIRE d.email IS UNIQUE"),

        # FileVer: unique by (sha, path) - specific file version at specific commit
        ("file_ver_sha_path", "FileVer", "(sha, path)",
         "CREATE CONSTRAINT file_ver_sha_path IF NOT EXISTS FOR (fv:FileVer) REQUIRE (fv.sha, fv.path) IS UNIQUE"),

        # ExternalDependency: unique by import_path
        ("external_dependency_path", "ExternalDependency", "import_path",
         "CREATE CONSTRAINT external_dependency_path IF NOT EXISTS FOR (ed:ExternalDependency) REQUIRE ed.import_path IS UNIQUE"),

        # CVE: unique by CVE ID
        ("cve_id", "CVE", "cve_id",
         "CREATE CONSTRAINT cve_id IF NOT EXISTS FOR (cve:CVE) REQUIRE cve.cve_id IS UNIQUE"),

        # Component: unique by (name, version)
        ("component_name_version", "Component", "(name, version)",
         "CREATE CONSTRAINT component_name_version IF NOT EXISTS FOR (comp:Component) REQUIRE (comp.name, comp.version) IS UNIQUE"),
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
        # Class and Interface method counts for complexity queries
        ("class_estimated_lines", "Class",
         "CREATE INDEX class_estimated_lines IF NOT EXISTS FOR (c:Class) ON (c.estimated_lines)"),

        ("interface_method_count", "Interface",
         "CREATE INDEX interface_method_count IF NOT EXISTS FOR (i:Interface) ON (i.method_count)"),

        # Method properties for centrality and hotspot analysis
        ("method_estimated_lines", "Method",
         "CREATE INDEX method_estimated_lines IF NOT EXISTS FOR (m:Method) ON (m.estimated_lines)"),

        ("method_is_public", "Method",
         "CREATE INDEX method_is_public IF NOT EXISTS FOR (m:Method) ON (m.is_public)"),

        ("method_is_static", "Method",
         "CREATE INDEX method_is_static IF NOT EXISTS FOR (m:Method) ON (m.is_static)"),

        ("method_class", "Method",
         "CREATE INDEX method_class IF NOT EXISTS FOR (m:Method) ON (m.class)"),

        # File properties for hotspot analysis
        ("file_total_lines", "File",
         "CREATE INDEX file_total_lines IF NOT EXISTS FOR (f:File) ON (f.total_lines)"),

        ("file_class_count", "File",
         "CREATE INDEX file_class_count IF NOT EXISTS FOR (f:File) ON (f.class_count)"),

        # Commit date for temporal analysis
        ("commit_date", "Commit",
         "CREATE INDEX commit_date IF NOT EXISTS FOR (c:Commit) ON (c.date)"),

        # Centrality scores (will be created when centrality analysis runs)
        ("method_pagerank", "Method",
         "CREATE INDEX method_pagerank IF NOT EXISTS FOR (m:Method) ON (m.pagerank_score)"),

        ("method_betweenness", "Method",
         "CREATE INDEX method_betweenness IF NOT EXISTS FOR (m:Method) ON (m.betweenness_score)"),

        # Similarity community for community analysis
        ("method_similarity_community", "Method",
         "CREATE INDEX method_similarity_community IF NOT EXISTS FOR (m:Method) ON (m.similarityCommunity)"),
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
            'name': record.get('name', 'Unknown'),
            'type': record.get('type', 'Unknown'),
            'entityType': record.get('entityType', 'Unknown'),
            'labelsOrTypes': record.get('labelsOrTypes', []),
            'properties': record.get('properties', [])
        }
        existing_constraints.append(constraint_info)

    logger.info(f"Found {len(existing_constraints)} existing constraints:")
    for constraint in existing_constraints:
        labels = ','.join(constraint['labelsOrTypes']) if constraint['labelsOrTypes'] else 'N/A'
        props = ','.join(constraint['properties']) if constraint['properties'] else 'N/A'
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
            'name': record.get('name', 'Unknown'),
            'type': record.get('type', 'Unknown'),
            'entityType': record.get('entityType', 'Unknown'),
            'labelsOrTypes': record.get('labelsOrTypes', []),
            'properties': record.get('properties', []),
            'state': record.get('state', 'Unknown')
        }
        existing_indexes.append(index_info)

    logger.info(f"Found {len(existing_indexes)} existing indexes:")
    for index in existing_indexes:
        labels = ','.join(index['labelsOrTypes']) if index['labelsOrTypes'] else 'N/A'
        props = ','.join(index['properties']) if index['properties'] else 'N/A'
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

    return {
        'constraints': constraints,
        'indexes': indexes
    }


if __name__ == "__main__":
    """
    Standalone script to setup schema on an existing database.
    """
    import argparse
    from common import setup_logging, create_neo4j_driver, add_common_args

    parser = argparse.ArgumentParser(description="Setup database schema constraints and indexes")
    add_common_args(parser)
    parser.add_argument("--verify-only", action="store_true",
                       help="Only verify existing schema, don't create new constraints/indexes")

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
