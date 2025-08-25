#!/usr/bin/env python3
"""
Schema Management for neo4j-code-graph

Centralizes the creation of constraints and indexes for all node types
based on their natural keys. This ensures data integrity and performance.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Central lists to avoid duplication across create/drop/verify
SCHEMA_CONSTRAINTS: list[tuple[str, str, str, str]] = [
    (
        "directory_path",
        "Directory",
        "path",
        "CREATE CONSTRAINT directory_path IF NOT EXISTS FOR (d:Directory) REQUIRE d.path IS UNIQUE",
    ),
    (
        "file_path",
        "File",
        "path",
        "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
    ),
    ("file_name", "File", "name", "CREATE INDEX file_name IF NOT EXISTS FOR (f:File) ON (f.name)"),
    (
        "class_name_file",
        "Class",
        "(name, file)",
        "CREATE CONSTRAINT class_name_file IF NOT EXISTS FOR (c:Class) REQUIRE (c.name, c.file) IS UNIQUE",
    ),
    (
        "interface_name_file",
        "Interface",
        "(name, file)",
        "CREATE CONSTRAINT interface_name_file IF NOT EXISTS FOR (i:Interface) REQUIRE (i.name, i.file) IS UNIQUE",
    ),
    (
        "method_signature_unique",
        "Method",
        "method_signature",
        "CREATE CONSTRAINT method_signature_unique IF NOT EXISTS FOR (m:Method) REQUIRE m.method_signature IS UNIQUE",
    ),
    (
        "method_id_required",
        "Method",
        "id",
        "CREATE CONSTRAINT method_id_required IF NOT EXISTS FOR (m:Method) REQUIRE m.id IS NOT NULL",
    ),
    (
        "method_signature_required",
        "Method",
        "method_signature",
        "CREATE CONSTRAINT method_signature_required IF NOT EXISTS FOR (m:Method) REQUIRE m.method_signature IS NOT NULL",
    ),
    (
        "commit_sha",
        "Commit",
        "sha",
        "CREATE CONSTRAINT commit_sha IF NOT EXISTS FOR (c:Commit) REQUIRE c.sha IS UNIQUE",
    ),
    (
        "developer_email",
        "Developer",
        "email",
        "CREATE CONSTRAINT developer_email IF NOT EXISTS FOR (d:Developer) REQUIRE d.email IS UNIQUE",
    ),
    (
        "file_ver_sha_path",
        "FileVer",
        "(sha, path)",
        "CREATE CONSTRAINT file_ver_sha_path IF NOT EXISTS FOR (fv:FileVer) REQUIRE (fv.sha, fv.path) IS UNIQUE",
    ),
    (
        "external_dependency_package",
        "ExternalDependency",
        "package",
        "CREATE CONSTRAINT external_dependency_package IF NOT EXISTS FOR (ed:ExternalDependency) REQUIRE ed.package IS UNIQUE",
    ),
    (
        "import_path",
        "Import",
        "import_path",
        "CREATE CONSTRAINT import_path IF NOT EXISTS FOR (i:Import) REQUIRE i.import_path IS UNIQUE",
    ),
    (
        "cve_id_unique",
        "CVE",
        "id",
        "CREATE CONSTRAINT cve_id_unique IF NOT EXISTS FOR (cve:CVE) REQUIRE cve.id IS UNIQUE",
    ),
]

SCHEMA_INDEXES: list[tuple[str, str, str]] = [
    (
        "class_estimated_lines",
        "Class",
        "CREATE INDEX class_estimated_lines IF NOT EXISTS FOR (c:Class) ON (c.estimated_lines)",
    ),
    (
        "interface_method_count",
        "Interface",
        "CREATE INDEX interface_method_count IF NOT EXISTS FOR (i:Interface) ON (i.method_count)",
    ),
    (
        "method_estimated_lines",
        "Method",
        "CREATE INDEX method_estimated_lines IF NOT EXISTS FOR (m:Method) ON (m.estimated_lines)",
    ),
    ("method_name", "Method", "CREATE INDEX method_name IF NOT EXISTS FOR (m:Method) ON (m.name)"),
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
        "method_name_class_name",
        "Method",
        "CREATE INDEX method_name_class_name IF NOT EXISTS FOR (m:Method) ON (m.name, m.class_name)",
    ),
    (
        "method_file_line",
        "Method",
        "CREATE INDEX method_file_line IF NOT EXISTS FOR (m:Method) ON (m.file, m.line)",
    ),
    (
        "method_name_file_line",
        "Method",
        "CREATE INDEX method_name_file_line IF NOT EXISTS FOR (m:Method) ON (m.name, m.file, m.line)",
    ),
    (
        "class_name_file_composite",
        "Class",
        "CREATE INDEX class_name_file_composite IF NOT EXISTS FOR (c:Class) ON (c.name, c.file)",
    ),
    ("commit_date", "Commit", "CREATE INDEX commit_date IF NOT EXISTS FOR (c:Commit) ON (c.date)"),
    (
        "method_pagerank",
        "Method",
        "CREATE INDEX method_pagerank IF NOT EXISTS FOR (m:Method) ON (m.pagerank_score)",
    ),
    (
        "method_betweenness",
        "Method",
        "CREATE INDEX method_betweenness IF NOT EXISTS FOR (m:Method) ON (m.betweenness_score)",
    ),
    (
        "method_similarity_community",
        "Method",
        "CREATE INDEX method_similarity_community IF NOT EXISTS FOR (m:Method) ON (m.similarityCommunity)",
    ),
]


def create_schema_constraints_and_indexes(session: Any) -> None:
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

    from src.data.cypher_builders import iter_schema_constraint_cypher

    for constraint_name, cypher in iter_schema_constraint_cypher():
        try:
            session.run(cypher)
            logger.info(f"✅ Created constraint {constraint_name}")
        except Exception as e:
            if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                logger.debug(f"  ⚠️  Constraint {constraint_name} already exists")
            else:
                logger.warning(f"  ❌ Failed to create constraint {constraint_name}: {e}")

    # =============================================================================
    # PERFORMANCE INDEXES (for commonly queried properties)
    # =============================================================================

    from src.data.cypher_builders import iter_schema_index_cypher

    for index_name, cypher in iter_schema_index_cypher():
        try:
            session.run(cypher)
            logger.info(f"✅ Created index {index_name}")
        except Exception as e:
            if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                logger.debug(f"  ⚠️  Index {index_name} already exists")
            else:
                logger.warning(f"  ❌ Failed to create index {index_name}: {e}")

    logger.info("Schema setup completed")


def verify_schema_constraints(session: Any) -> list[dict[str, Any]]:
    """
    Verify that all expected constraints exist in the database.
    Returns a report of existing constraints.
    """

    logger.info("Verifying schema constraints...")

    # Get all constraints
    result = session.run("SHOW CONSTRAINTS")
    existing_constraints: list[dict[str, Any]] = []

    for record in result:
        rec: dict[str, Any] = dict(record)
        constraint_info: dict[str, Any] = {
            "name": rec.get("name", "Unknown"),
            "type": rec.get("type", "Unknown"),
            "entityType": rec.get("entityType", "Unknown"),
            "labelsOrTypes": rec.get("labelsOrTypes", []),
            "properties": rec.get("properties", []),
        }
        existing_constraints.append(constraint_info)

    logger.info(f"Found {len(existing_constraints)} existing constraints:")
    for constraint in existing_constraints:
        labels = ",".join(constraint["labelsOrTypes"]) if constraint["labelsOrTypes"] else "N/A"
        props = ",".join(constraint["properties"]) if constraint["properties"] else "N/A"
        logger.info(f"  • {constraint['name']}: {constraint['type']} on {labels}({props})")

    return existing_constraints


def verify_schema_indexes(session: Any) -> list[dict[str, Any]]:
    """
    Verify that all expected indexes exist in the database.
    Returns a report of existing indexes.
    """

    logger.info("Verifying schema indexes...")

    # Get all indexes
    result = session.run("SHOW INDEXES")
    existing_indexes: list[dict[str, Any]] = []

    for record in result:
        rec: dict[str, Any] = dict(record)
        index_info: dict[str, Any] = {
            "name": rec.get("name", "Unknown"),
            "type": rec.get("type", "Unknown"),
            "entityType": rec.get("entityType", "Unknown"),
            "labelsOrTypes": rec.get("labelsOrTypes", []),
            "properties": rec.get("properties", []),
            "state": rec.get("state", "Unknown"),
        }
        existing_indexes.append(index_info)

    logger.info(f"Found {len(existing_indexes)} existing indexes:")
    for index in existing_indexes:
        labels = ",".join(index["labelsOrTypes"]) if index["labelsOrTypes"] else "N/A"
        props = ",".join(index["properties"]) if index["properties"] else "N/A"
        logger.info(f"  • {index['name']}: {index['type']} on {labels}({props}) - {index['state']}")

    return existing_indexes


def validate_schema_consistency(session: Any) -> dict[str, list[str]]:
    """
    Validate schema consistency and check for potential issues.
    Returns a report of findings and recommendations.
    """
    logger.info("🔍 Validating schema consistency...")

    issues: list[str] = []
    recommendations: list[str] = []

    # Check for reserved word usage in property names
    # Note: 'class' is a reserved word that should be avoided in property names

    # Check Method.class property usage
    try:
        result = session.run("MATCH (m:Method) WHERE m.class IS NOT NULL RETURN count(m) as count")
        single = result.single()
        count = int(single["count"]) if single and "count" in single else 0
        if count > 0:
            issues.append(f"⚠️  Found {count} Method nodes using reserved 'class' property")
            recommendations.append(
                "Consider renaming 'class' property to 'class_name' or 'declaring_class'"
            )
    except Exception as e:
        logger.warning(f"Could not check class property: {e}")

    # Check for unused indexes
    try:
        result = session.run("SHOW INDEXES")
        for record in result:
            rec = dict(record)
            index_name = rec.get("name", "")
            if "is_abstract" in index_name or "is_private" in index_name:
                recommendations.append(f"Consider removing unused boolean index: {index_name}")
    except Exception as e:
        logger.warning(f"Could not check indexes: {e}")

    # Check for missing composite indexes on commonly queried patterns
    common_patterns = [
        ("Method", ["name", "class"], "method_name_class"),
        ("Method", ["file", "line"], "method_file_line"),
        ("Class", ["name", "file"], "class_name_file_composite"),
    ]

    for node_type, properties, expected_index in common_patterns:
        try:
            # This is a simplified check - in practice you'd want to analyze query patterns
            recommendations.append(
                f"Ensure composite index exists: {expected_index} on {node_type}({','.join(properties)})"
            )
        except Exception as e:
            logger.warning(f"Could not check {expected_index}: {e}")

    # Report findings
    if issues:
        logger.warning("Found schema issues:")
        for issue in issues:
            logger.warning(f"  {issue}")

    if recommendations:
        logger.info("Schema recommendations:")
        for rec in recommendations:
            logger.info(f"  • {rec}")

    return {"issues": issues, "recommendations": recommendations}


def setup_complete_schema(session: Any) -> dict[str, list[dict[str, Any]]]:
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


def ensure_constraints_exist_or_fail(session: Any) -> None:
    """
    Fail-fast guard: ensure core constraints exist before any data load.

    - If required constraints are missing, attempt to create the full schema
      (constraints + indexes) and re-verify.
    - If still missing, raise an error to abort the load.
    """

    required_constraint_names = {
        name
        for name, _label, _props, _cypher in SCHEMA_CONSTRAINTS
        if name
        in {
            "directory_path",
            "file_path",
            "class_name_file",
            "interface_name_file",
            "method_signature_unique",
            "commit_sha",
            "developer_email",
            "file_ver_sha_path",
            "import_path",
            "cve_id_unique",
        }
    }

    existing = verify_schema_constraints(session)
    existing_names = {c.get("name", "") for c in existing}
    missing = required_constraint_names - existing_names

    if not missing:
        return

    logger.warning(
        "Required constraints missing (%s). Attempting to create complete schema...",
        ", ".join(sorted(missing)),
    )
    create_schema_constraints_and_indexes(session)
    # Re-verify
    existing_after = verify_schema_constraints(session)
    existing_after_names = {c.get("name", "") for c in existing_after}
    still_missing = required_constraint_names - existing_after_names
    if still_missing:
        raise RuntimeError(
            "Schema constraints missing after setup: " + ", ".join(sorted(still_missing))
        )


def drop_managed_schema(session: Any) -> None:
    """
    Drop only constraints and indexes that this project manages, based on
    SCHEMA_CONSTRAINTS and SCHEMA_INDEXES. Does not touch user-created schema.
    """
    logger.info("🧹 Dropping managed schema (constraints + indexes)...")
    # Drop constraints first (to avoid index dependencies)
    for constraint_name, _label, _props, _ in SCHEMA_CONSTRAINTS:
        try:
            session.run(f"DROP CONSTRAINT {constraint_name} IF EXISTS").consume()
            logger.info(f"  ✅ Dropped constraint {constraint_name}")
        except Exception as e:
            logger.debug(f"  ⚠️  Could not drop constraint {constraint_name}: {e}")
    # Drop indexes
    for index_name, _label, _ in SCHEMA_INDEXES:
        try:
            session.run(f"DROP INDEX {index_name} IF EXISTS").consume()
            logger.info(f"  ✅ Dropped index {index_name}")
        except Exception as e:
            logger.debug(f"  ⚠️  Could not drop index {index_name}: {e}")


def main():
    """
    Main entry point for schema management CLI.
    """
    import argparse

    # Imports below support both installed package and repo run contexts
    # Use absolute imports to avoid context-dependent failures
    from src.utils.common import add_common_args, create_neo4j_driver, setup_logging

    parser = argparse.ArgumentParser(description="Setup database schema constraints and indexes")
    add_common_args(parser)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing schema, don't create new constraints/indexes",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run schema validation and provide recommendations",
    )

    args = parser.parse_args()
    setup_logging(args.log_level, args.log_file)

    with create_neo4j_driver(args.uri, args.username, args.password) as driver:
        with driver.session(database=args.database) as session:
            if args.validate:
                validate_schema_consistency(session)
            elif args.verify_only:
                verify_schema_constraints(session)
                verify_schema_indexes(session)
            else:
                setup_complete_schema(session)


if __name__ == "__main__":
    main()
