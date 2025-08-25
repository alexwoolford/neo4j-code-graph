"""
Pipeline progress inspection utilities and CLI.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from src.utils.common import create_neo4j_driver, get_neo4j_config, setup_logging

logger = logging.getLogger(__name__)


def check_database_state(driver: Any, database: str) -> dict[str, Any]:
    """Return a summary of node/relationship counts and progress indicators."""
    with driver.session(database=database) as session:  # type: ignore[reportUnknownMemberType]
        print("🔍 NEO4J DATABASE STATE CHECK")
        print("=" * 50)

        # Get basic node counts
        result = session.run(
            """
            CALL db.labels() YIELD label
            WITH label
            CALL apoc.cypher.run('MATCH (n:' + label + ') RETURN count(n) as count', {})
            YIELD value
            RETURN label, value.count as count
            ORDER BY count DESC
        """
        )

        print("\n📊 NODE COUNTS BY TYPE:")
        total_nodes = 0
        node_types: dict[str, int] = {}
        for record in result:
            count = record["count"]
            label = record["label"]
            node_types[str(label)] = int(count)
            total_nodes += int(count)
            print(f"  {label}: {int(count):,}")

        print(f"\n📈 TOTAL NODES: {total_nodes:,}")

        # Check relationships
        print("\n🔗 RELATIONSHIP COUNTS:")
        result = session.run(
            """
            CALL db.relationshipTypes() YIELD relationshipType
            WITH relationshipType
            CALL apoc.cypher.run(
                'MATCH ()-[r:' + relationshipType + ']->() RETURN count(r) as count', {}
            )
            YIELD value
            RETURN relationshipType, value.count as count
            ORDER BY count DESC
        """
        )

        total_rels = 0
        rel_types: dict[str, int] = {}
        for record in result:
            count = int(record["count"])
            rel_type = str(record["relationshipType"])
            rel_types[rel_type] = count
            total_rels += count
            print(f"  {rel_type}: {count:,}")

        print(f"\n📈 TOTAL RELATIONSHIPS: {total_rels:,}")

        # Check specific progress indicators
        print("\n🎯 PROCESSING PROGRESS:")

        # Files with embeddings
        result = session.run(
            "MATCH (f:File) WHERE f.embedding IS NOT NULL RETURN count(f) as count"
        )
        single = result.single()
        files_with_embeddings = int(single["count"]) if single and "count" in single else 0
        total_files = int(node_types.get("File", 0))
        print(f"  Files with embeddings: {files_with_embeddings:,} / {total_files:,}")

        # Methods with embeddings
        result = session.run(
            "MATCH (m:Method) WHERE m.embedding IS NOT NULL RETURN count(m) as count"
        )
        single = result.single()
        methods_with_embeddings = int(single["count"]) if single and "count" in single else 0
        total_methods = int(node_types.get("Method", 0))
        print(f"  Methods with embeddings: {methods_with_embeddings:,} / {total_methods:,}")

        # Import relationships
        imports_count = int(rel_types.get("IMPORTS", 0))
        print(f"  Import relationships: {imports_count:,}")

        # Method calls
        calls_count = int(rel_types.get("CALLS", 0))
        print(f"  Method call relationships: {calls_count:,}")

        # Status summary
        print("\n✅ STATUS ASSESSMENT:")

        if total_files > 0 and files_with_embeddings == total_files:
            print("  ✅ File processing: COMPLETE")
        elif total_files > 0:
            print(f"  ⚠️  File processing: PARTIAL ({files_with_embeddings}/{total_files})")
        else:
            print("  ❌ File processing: NOT STARTED")

        if total_methods > 0 and methods_with_embeddings == total_methods:
            print("  ✅ Method processing: COMPLETE")
        elif total_methods > 0:
            print(f"  ⚠️  Method processing: PARTIAL ({methods_with_embeddings}/{total_methods})")
        else:
            print("  ❌ Method processing: NOT STARTED")

        if imports_count > 0:
            print("  ✅ Import processing: COMPLETE")
        else:
            print("  ❌ Import processing: NOT STARTED")

        if calls_count > 0:
            print(f"  ⚠️  Method calls: PARTIAL ({calls_count:,} created)")
        else:
            print("  ❌ Method calls: NOT STARTED")

        return {
            "node_types": node_types,
            "rel_types": rel_types,
            "total_nodes": total_nodes,
            "total_rels": total_rels,
            "files_complete": total_files > 0 and files_with_embeddings == total_files,
            "methods_complete": total_methods > 0 and methods_with_embeddings == total_methods,
            "imports_complete": imports_count > 0,
            "calls_partial": calls_count > 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Neo4j database state")
    parser.add_argument("--uri", help="Neo4j URI")
    parser.add_argument("--username", help="Neo4j username")
    parser.add_argument("--password", help="Neo4j password")
    parser.add_argument("--database", default="neo4j", help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    setup_logging(args.log_level)

    # Get config
    if args.uri:
        config = (args.uri, args.username, args.password, args.database)
    else:
        config = get_neo4j_config()

    with create_neo4j_driver(config[0], config[1], config[2]) as driver:
        state = check_database_state(driver, config[3])

        print("\n💡 RECOMMENDATIONS:")
        if state["files_complete"] and state["methods_complete"] and state["imports_complete"]:
            print("  🚀 Ready for: similarity analysis, CVE analysis, etc.")
        else:
            print("  ⚠️  Consider re-running: code-graph-code-to-graph <repo-path>")


if __name__ == "__main__":
    main()
