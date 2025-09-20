#!/usr/bin/env python3
"""
CVE Analysis Demo Queries - Multi-Modal Neo4j Access Patterns

✅ This file contains WORKING examples using the actual graph schema.

    Schema: CVE -[:AFFECTS]-> ExternalDependency

This script demonstrates various Neo4j access patterns for CVE analysis:
1. Graph Traversal - Find dependency paths from CVEs to public APIs
2. Vector Search - Find similar dependencies using embeddings
3. Lucene Search - Text search CVE descriptions
4. Graph Algorithms - PageRank, community detection for risk prioritization
5. Hybrid Queries - Combining multiple signals for risk assessment

Run after: python cve_analysis.py
"""

import os
import sys
from collections.abc import Iterable
from typing import Any

from graphdatascience import GraphDataScience
from neo4j import GraphDatabase
from neo4j import Session as NeoSession

try:
    from src.utils.neo4j_utils import get_neo4j_config
except Exception:
    # Repo-local fallback when executed without installation
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from src.utils.neo4j_utils import get_neo4j_config  # type: ignore

# Get connection settings using proper configuration
NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()


def demo_graph_traversal(session: NeoSession) -> None:
    """Demonstrate graph traversal for CVE impact analysis."""
    print("🔍 1. GRAPH TRAVERSAL: CVE Impact via Dependency Chains")
    print("=" * 60)

    # Find critical paths from vulnerabilities to public APIs
    query = """
    // Find all paths from CVE-affected dependencies to public APIs
    MATCH (cve:CVE)-[:AFFECTS]->(ed:ExternalDependency)
    MATCH (ed)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
    WHERE f.path CONTAINS "api"
       OR f.path CONTAINS "controller"
       OR f.path CONTAINS "rest"

    OPTIONAL MATCH (f)-[:DECLARES]->(m:Method {is_public: true})

    RETURN cve.cve_id AS cve_id,
           cve.cvss_score AS severity,
           ed.package AS vulnerable_dependency,
           f.path AS exposed_file,
           collect(DISTINCT m.name)[0..3] AS public_methods
    ORDER BY cve.cvss_score DESC
    LIMIT 20
    """

    result = session.run(query)
    for record in result:
        print(f"🚨 {record['cve_id']}")
        print(f"   Severity: {record['severity']}")
        print(f"   Vulnerable Dependency: {record['vulnerable_dependency']}")
        print(f"   Exposed File: {record['exposed_file']}")
        print(f"   Public Methods: {record['public_methods']}")
        print()


def demo_vector_search(session: NeoSession) -> None:
    """Demonstrate vector similarity search for dependencies."""
    print("\n🎯 2. VECTOR SEARCH: Find Similar Vulnerable Dependencies")
    print("=" * 60)

    # First, get a vulnerable dependency's embedding
    vuln_component = session.run(
        """
        MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)
        WHERE dep.embedding IS NOT NULL
        RETURN dep.gav AS name, dep.embedding AS embedding
        LIMIT 1
        """
    ).single()

    if vuln_component:
        # Find similar dependencies by group/artifact pattern matching
        query = """
        MATCH (dep:ExternalDependency)
        WHERE dep.gav <> $comp_name
          AND (dep.group_id = split($comp_name, ':')[0]
               OR dep.artifact_id CONTAINS split(split($comp_name, ':')[1], '/')[0])
        WITH dep,
             CASE
               WHEN dep.group_id = split($comp_name, ':')[0] THEN 0.8
               ELSE 0.3
             END AS similarity_score

        // Check if similar dependencies are used in the codebase
        OPTIONAL MATCH (dep)<-[:DEPENDS_ON]-(i:Import)
        OPTIONAL MATCH (i)<-[:IMPORTS]-(file:File)

        RETURN dep.gav AS similar_dependency,
               round(similarity_score, 3) AS similarity_score,
               count(DISTINCT file) AS usage_count,
               collect(DISTINCT file.language)[0..3] AS sample_languages
        ORDER BY similarity_score DESC, usage_count DESC
        LIMIT 5
        """

        result = session.run(query, comp_name=vuln_component.get("name"))

        print(f"Dependencies similar to vulnerable: {vuln_component.get('name')}")
        print()

        for record in result:
            print(f"📦 {record['similar_dependency']}")
            print(f"   Similarity: {record['similarity_score']}")
            print(f"   Used in {record['usage_count']} files")
            print(f"   Languages: {record['sample_languages']}")
            print()


def demo_lucene_search(session: NeoSession) -> None:
    """Demonstrate full-text search for related vulnerabilities."""
    print("\n🔎 3. LUCENE SEARCH: Find Related CVEs by Description")
    print("=" * 60)

    # Search for CVEs with similar vulnerability patterns
    search_terms = ["sql injection", "buffer overflow", "authentication bypass"]

    for term in search_terms:
        print(f"Searching for: {term}")

        query = """
        CALL db.index.fulltext.queryNodes('cve_description_index', $search_term)
        YIELD node, score
        WHERE score > 0.5

        // Find what dependencies are affected
        MATCH (node)-[:AFFECTS]->(dep:ExternalDependency)
        OPTIONAL MATCH (ed:ExternalDependency)-[:RESOLVED_TO]->(comp)
        OPTIONAL MATCH (file:File)-[:DEPENDS_ON]->(ed)

        RETURN node.cve_id AS cve_id,
               node.cvss_score AS cvss_score,
               round(score, 3) AS search_relevance,
               collect(DISTINCT dep.gav)[0..3] AS affected_dependencies,
               count(DISTINCT file) AS codebase_usage
        ORDER BY score DESC
        LIMIT 3
        """

        result = session.run(query, search_term=term)
        for record in result:
            print(f"  🔍 {record['cve_id']} (CVSS: {record['cvss_score']})")
            print(f"     Relevance: {record['search_relevance']}")
            print(f"     Dependencies: {record['affected_dependencies']}")
            print(f"     Codebase usage: {record['codebase_usage']} files")
        print()


def demo_graph_algorithms(gds: GraphDataScience) -> None:
    """Demonstrate graph algorithms for dependency analysis."""
    print("\n📊 4. GRAPH ALGORITHMS: Dependency Importance & Communities")
    print("=" * 60)

    # Create dependency graph projection
    try:
        gds.run_cypher(
            "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
            name="dependency_analysis",
        )
    except Exception:
        # Graph doesn't exist yet, which is fine
        print("Note: dependency_analysis graph doesn't exist yet (normal for first run)")

    dependency_graph, _ = gds.graph.project.cypher(
        "dependency_analysis",
        """
        MATCH (n)
        WHERE n:File OR n:ExternalDependency
        RETURN id(n) AS id,
               CASE
                 WHEN n:ExternalDependency THEN 'ExternalDep'
                 ELSE 'File'
               END AS nodeType,
               COALESCE(n.name, n.path, n.import_path) AS name
        """,
        """
        MATCH (source)-[r:DEPENDS_ON|RESOLVED_TO]->(target)
        RETURN id(source) AS source, id(target) AS target,
               type(r) AS relationshipType
        """,
    )

    print("Graph projection created with:")
    print(f"  Nodes: {dependency_graph.node_count()}")
    print(f"  Relationships: {dependency_graph.relationship_count()}")
    print()

    # Run PageRank to find most influential dependencies
    print("Running PageRank analysis...")
    pagerank_result: Any = gds.pageRank.stream(dependency_graph)
    top_dependencies: Any = pagerank_result.nlargest(10, "score")

    print("🏆 Most Influential Dependencies:")
    for _idx, row in cast_iterrows(top_dependencies):
        print(f"   Score: {row['score']:.4f} - Node ID: {row['nodeId']}")
    print()

    # Run Louvain community detection
    print("Running community detection...")
    louvain_result: Any = gds.louvain.stream(dependency_graph)
    communities: Any = louvain_result.groupby("communityId").size()
    try:
        communities = communities.sort_values(ascending=False)  # type: ignore[call-arg]
    except Exception:
        pass

    print("🏘️  Dependency Communities:")
    try:
        for community_id, size in communities.head(5).items():
            print(f"   Community {community_id}: {size} nodes")
    except Exception:
        # Best-effort printing if the return type is not a pandas Series
        pass
    print()

    # Clean up
    dependency_graph.drop()


def cast_iterrows(df_like: Any) -> Iterable[tuple[Any, Any]]:
    """Helper to satisfy static typing for iterrows in examples."""
    try:
        return df_like.iterrows()
    except Exception:
        return []


def demo_hybrid_queries(session: NeoSession) -> None:
    """Demonstrate hybrid queries combining multiple access patterns."""
    print("\n🔄 5. HYBRID QUERIES: Combining Multiple Access Patterns")
    print("=" * 60)

    # Complex query combining traversal, centrality, and text search
    query = """
    // Find high-risk vulnerabilities using multiple signals
            MATCH (cve:CVE)-[:AFFECTS]->(vuln_dep:ExternalDependency)
    WHERE cve.cvss_score >= 7.0  // High severity only

    // Graph traversal: Find dependency paths to public APIs
    OPTIONAL MATCH path = (api_file:File)-[:DEPENDS_ON*1..3]->(ed:ExternalDependency)-[:RESOLVED_TO]->(vuln_dep)
    WHERE api_file.package CONTAINS "api"
       OR api_file.package CONTAINS "controller"

    WITH cve, vuln_dep,
         count(DISTINCT path) AS api_exposure_count,
         min(length(path)) AS shortest_path_to_api

    // Dependency similarity: Use pattern matching instead of embedding similarity
    // (Embedding similarity should be calculated using GDS Python client, not in Cypher)
    OPTIONAL MATCH (similar:ExternalDependency)
    WHERE similar <> vuln_dep
      AND similar.group_id = vuln_dep.group_id
      AND similar.artifact_id = vuln_dep.artifact_id

    WITH cve, vuln_dep, api_exposure_count, shortest_path_to_api,
         count(DISTINCT similar) AS similar_dependency_count

    // Calculate composite risk score
    WITH cve, vuln_dep,
         api_exposure_count,
         shortest_path_to_api,
         similar_dependency_count,
         // Risk formula combining multiple factors
         (cve.cvss_score *
          CASE WHEN api_exposure_count > 0 THEN 2.0 ELSE 1.0 END *
          CASE WHEN shortest_path_to_api <= 2 THEN 1.5 ELSE 1.0 END *
          (1 + similar_dependency_count * 0.2)
         ) AS composite_risk_score

    // Text search: Check for known attack patterns
    WITH cve, vuln_dep, api_exposure_count, shortest_path_to_api,
         similar_dependency_count, composite_risk_score,
         CASE
           WHEN toLower(cve.description) CONTAINS "remote code execution" THEN true
           WHEN toLower(cve.description) CONTAINS "sql injection" THEN true
           WHEN toLower(cve.description) CONTAINS "authentication bypass" THEN true
           ELSE false
         END AS has_critical_keywords

    WHERE api_exposure_count > 0 OR composite_risk_score > 15.0

    RETURN cve.cve_id AS vulnerability,
           vuln_dep.gav AS dependency,
           round(cve.cvss_score, 1) AS cvss_score,
           api_exposure_count AS api_exposures,
           shortest_path_to_api AS min_path_length,
           similar_dependency_count AS similar_dependencies,
           round(composite_risk_score, 2) AS risk_score,
           has_critical_keywords AS critical_attack_pattern
    ORDER BY composite_risk_score DESC
    LIMIT 10
    """

    result = session.run(query)

    print("🚨 High-Risk Vulnerabilities (Composite Analysis):")
    print()

    for record in result:
        print(f"CVE: {record['vulnerability']}")
        print(f"  Dependency: {record['dependency']}")
        print(f"  CVSS Score: {record['cvss_score']}")
        print(f"  API Exposures: {record['api_exposures']}")
        print(f"  Min Path to API: {record['min_path_length']} hops")
        print(f"  Similar Dependencies: {record['similar_dependencies']}")
        print(f"  Composite Risk: {record['risk_score']}")
        print(f"  Critical Pattern: {record['critical_attack_pattern']}")
        print("-" * 40)


def main() -> None:
    """Run all CVE analysis demonstrations."""
    print("🛡️  CVE ANALYSIS DEMO - Multi-Modal Neo4j Access Patterns")
    print("=" * 70)
    print()

    # Connect to Neo4j
    gds = GraphDataScience(
        NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD), database=NEO4J_DATABASE
    )

    try:
        with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)) as driver:
            with driver.session(database=NEO4J_DATABASE) as session:
                # Check if we have data
                cve_single: Any | None = session.run(
                    "MATCH (cve:CVE) RETURN count(cve) AS cve_count"
                ).single()
                cve_count = (
                    int(cve_single["cve_count"]) if cve_single and "cve_count" in cve_single else 0
                )
                if cve_count == 0:
                    print("❌ No CVE data found. Please run: python cve_analysis.py first")
                    return

                print(f"✅ Found {cve_count} CVEs in database")
                print()

                # Run demonstrations
                demo_graph_traversal(session)
                demo_vector_search(session)
                demo_lucene_search(session)
                demo_graph_algorithms(gds)
                demo_hybrid_queries(session)

                print("\n🎉 CVE Analysis Demo Complete!")
                print("\nKey Takeaways:")
                print("• Graph traversal reveals dependency impact chains")
                print("• Pattern search finds similar vulnerable dependencies")
                print("• Lucene search identifies related vulnerability patterns")
                print("• Graph algorithms highlight critical architectural dependencies")
                print("• Hybrid queries combine multiple signals for comprehensive risk assessment")
    except Exception as e:
        print(f"❌ Demo failed: {e}")


if __name__ == "__main__":
    main()
