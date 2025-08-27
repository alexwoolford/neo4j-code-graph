#!/usr/bin/env python3
"""
Simple Neo4j connection test to help debug authentication issues.
"""

import os
import sys

from neo4j import GraphDatabase

from src.utils.common import get_neo4j_config

# Add project root to path for imports
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_neo4j_connection():
    """Test Neo4j connection with current settings."""

    # Use the proper config function that includes ensure_port fix
    uri, username, password, database = get_neo4j_config()

    print("🔍 Testing Neo4j Connection...")

    try:
        with GraphDatabase.driver(uri, auth=(username, password)) as driver:
            driver.verify_connectivity()

            with driver.session(database=database) as session:
                result = session.run("RETURN 'Connection successful!' AS message")
                record = result.single()
                msg = (
                    record["message"]
                    if record and "message" in record
                    else "Connection successful!"
                )
                print(f"✅ {msg}")

            # Test if we have any data
            count_query = """
            MATCH (n)
            RETURN count(n) AS total_nodes,
                   labels(n)[0] AS sample_label
            LIMIT 1
            """
            with driver.session(database=database) as session:
                result = session.run(count_query)
                rec = result.single()
                total_nodes = int(rec["total_nodes"]) if rec and "total_nodes" in rec else 0
                if total_nodes > 0:
                    print(f"📊 Database has {total_nodes} nodes")

                    labels_rec = session.run(
                        """
                        CALL db.labels() YIELD label
                        RETURN collect(label) AS labels
                        """
                    ).single()
                    node_types: list[str] = (
                        list(labels_rec["labels"]) if labels_rec and "labels" in labels_rec else []
                    )

                    print(f"📝 Node types: {node_types}")

                    if "File" in node_types:
                        print("✅ Code analysis data found - ready for CVE analysis!")
                    else:
                        print("⚠️  No code analysis data found")
                        print(
                            "   Run: code-graph-pipeline-prefect --repo-url <your-repo-url> first"
                        )
                else:
                    print("📊 Database is empty - run the pipeline first")

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print()
        print("💡 Troubleshooting:")
        print("1. Check your Neo4j password in .env file")
        print("2. Verify your Neo4j instance is running")
        print("3. Check network connectivity to Neo4j Aura")
        print("4. Verify the URI format is correct")


if __name__ == "__main__":
    test_neo4j_connection()
