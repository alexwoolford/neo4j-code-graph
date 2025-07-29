#!/usr/bin/env python3
"""
Check the current state of the Neo4j database to see what data has been loaded.
Useful for resuming after crashes or understanding pipeline progress.
"""

import argparse
import sys

sys.path.insert(0, "src")

from utils.common import create_neo4j_driver, get_neo4j_config


def check_database_state(driver, database):
    """Check what data exists in the database."""
    with driver.session(database=database) as session:
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
        node_types = {}
        for record in result:
            count = record["count"]
            label = record["label"]
            node_types[label] = count
            total_nodes += count
            print(f"  {label}: {count:,}")

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
        rel_types = {}
        for record in result:
            count = record["count"]
            rel_type = record["relationshipType"]
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
        files_with_embeddings = result.single()["count"]
        total_files = node_types.get("File", 0)
        print(f"  Files with embeddings: {files_with_embeddings:,} / {total_files:,}")

        # Methods with embeddings
        result = session.run(
            "MATCH (m:Method) WHERE m.embedding IS NOT NULL RETURN count(m) as count"
        )
        methods_with_embeddings = result.single()["count"]
        total_methods = node_types.get("Method", 0)
        print(f"  Methods with embeddings: {methods_with_embeddings:,} / {total_methods:,}")

        # Import relationships
        imports_count = rel_types.get("IMPORTS", 0)
        print(f"  Import relationships: {imports_count:,}")

        # Method calls
        calls_count = rel_types.get("CALLS", 0)
        print(f"  Method call relationships: {calls_count:,}")

        # Check if processing looks complete
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


def main():
    parser = argparse.ArgumentParser(description="Check Neo4j database state")
    parser.add_argument("--uri", help="Neo4j URI")
    parser.add_argument("--username", help="Neo4j username")
    parser.add_argument("--password", help="Neo4j password")
    parser.add_argument("--database", default="neo4j", help="Neo4j database")
    args = parser.parse_args()

    # Get config
    if args.uri:
        config = (args.uri, args.username, args.password, args.database)
    else:
        config = get_neo4j_config()

    with create_neo4j_driver(config[0], config[1], config[2]) as driver:
        state = check_database_state(driver, config[3])

        print("\n💡 RECOMMENDATIONS:")
        if state["files_complete"] and state["methods_complete"] and state["imports_complete"]:
            if state["calls_partial"]:
                print("  🔄 Resume with: python scripts/fix_method_calls.py")
            else:
                print("  🚀 Ready for: similarity analysis, CVE analysis, etc.")
        else:
            print("  ⚠️  Consider re-running: python scripts/code_to_graph.py <repo-url>")


if __name__ == "__main__":
    main()
