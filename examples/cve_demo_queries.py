#!/usr/bin/env python3
"""
CVE Analysis Demo Queries - Multi-Modal Neo4j Access Patterns

This script demonstrates various Neo4j access patterns for CVE analysis:
1. Graph Traversal - Find dependency paths from CVEs to public APIs
2. Vector Search - Find similar components using embeddings
3. Lucene Search - Text search CVE descriptions
4. Graph Algorithms - PageRank, community detection for risk prioritization
5. Hybrid Queries - Combining multiple signals for risk assessment

Run after: python cve_analysis.py
"""

from utils import get_neo4j_config
import os
import sys
from neo4j import GraphDatabase
from graphdatascience import GraphDataScience

# Add project root to path for imports
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# Get connection settings using proper configuration
NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()


def demo_graph_traversal(session):
    """Demonstrate graph traversal for CVE impact analysis."""
    print("🔍 1. GRAPH TRAVERSAL: CVE Impact via Dependency Chains")
    print("=" * 60)

    # Find critical paths from vulnerabilities to public APIs
    query = """
    // Find all paths from CVE-affected components to public APIs
    MATCH (cve:CVE)-[:AFFECTS]->(vuln_comp:Component)
    MATCH (ed:ExternalDependency)-[:RESOLVED_TO]->(vuln_comp)
    MATCH path = (public_file:File)-[:DEPENDS_ON*1..4]->(ed)
    WHERE public_file.package CONTAINS "api"
       OR public_file.package CONTAINS "controller"
       OR public_file.package CONTAINS "rest"

    // Calculate risk score based on path length and exposure
    WITH cve, vuln_comp, public_file, length(path) AS hops,
         CASE
           WHEN public_file.package CONTAINS "api" THEN 10
           WHEN public_file.package CONTAINS "controller" THEN 8
           WHEN public_file.package CONTAINS "rest" THEN 9
           ELSE 5
         END AS exposure_score

    // Risk = CVSS * Exposure / Distance
    WITH cve, vuln_comp, public_file, hops, exposure_score,
         (cve.cvss_score * exposure_score / hops) AS risk_score

    RETURN cve.cve_id AS vulnerability,
           vuln_comp.name AS vulnerable_component,
           public_file.path AS exposed_api_file,
           public_file.package AS api_package,
           hops AS dependency_distance,
           round(risk_score, 2) AS calculated_risk
    ORDER BY risk_score DESC
    LIMIT 10
    """

    result = session.run(query)
    for record in result:
        print(f"🚨 {record['vulnerability']}")
        print(f"   Component: {record['vulnerable_component']}")
        print(f"   Exposed API: {record['exposed_api_file']}")
        print(f"   Distance: {record['dependency_distance']} hops")
        print(f"   Risk Score: {record['calculated_risk']}")
        print()


def demo_vector_search(session):
    """Demonstrate vector similarity search for components."""
    print("\n🎯 2. VECTOR SEARCH: Find Similar Vulnerable Components")
    print("=" * 60)

    # First, get a vulnerable component's embedding
    vuln_component = session.run("""
        MATCH (cve:CVE)-[:AFFECTS]->(comp:Component)
        WHERE comp.embedding IS NOT NULL
        RETURN comp.name AS name, comp.embedding AS embedding
        LIMIT 1
    """).single()

    if vuln_component:
        # Use vector index to find similar components
        query = """
        CALL db.index.vector.queryNodes('component_embeddings', 5, $embedding)
        YIELD node, score
        WHERE node:Component AND node.name <> $comp_name

        // Check if similar components are also used in the codebase
        OPTIONAL MATCH (ed:ExternalDependency)-[:RESOLVED_TO]->(node)
        OPTIONAL MATCH (file:File)-[:DEPENDS_ON]->(ed)

        RETURN node.name AS similar_component,
               round(score, 3) AS similarity_score,
               count(DISTINCT file) AS usage_count,
               collect(DISTINCT file.package)[0..3] AS sample_packages
        ORDER BY score DESC
        """

        result = session.run(query,
                             embedding=vuln_component["embedding"],
                             comp_name=vuln_component["name"])

        print(f"Components similar to vulnerable: {vuln_component['name']}")
        print()

        for record in result:
            print(f"📦 {record['similar_component']}")
            print(f"   Similarity: {record['similarity_score']}")
            print(f"   Used in {record['usage_count']} files")
            print(f"   Packages: {record['sample_packages']}")
            print()


def demo_lucene_search(session):
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

        // Find what components are affected
        MATCH (node)-[:AFFECTS]->(comp:Component)
        OPTIONAL MATCH (ed:ExternalDependency)-[:RESOLVED_TO]->(comp)
        OPTIONAL MATCH (file:File)-[:DEPENDS_ON]->(ed)

        RETURN node.cve_id AS cve_id,
               node.cvss_score AS cvss_score,
               round(score, 3) AS search_relevance,
               collect(DISTINCT comp.name)[0..3] AS affected_components,
               count(DISTINCT file) AS codebase_usage
        ORDER BY score DESC
        LIMIT 3
        """

        result = session.run(query, search_term=term)
        for record in result:
            print(f"  🔍 {record['cve_id']} (CVSS: {record['cvss_score']})")
            print(f"     Relevance: {record['search_relevance']}")
            print(f"     Components: {record['affected_components']}")
            print(f"     Codebase usage: {record['codebase_usage']} files")
        print()


def demo_graph_algorithms(gds):
    """Demonstrate graph algorithms for dependency analysis."""
    print("\n📊 4. GRAPH ALGORITHMS: Component Importance & Communities")
    print("=" * 60)

    # Create dependency graph projection
    try:
        gds.graph.drop("dependency_analysis")
    except Exception:
        # Graph doesn't exist yet, which is fine
        print("Note: dependency_analysis graph doesn't exist yet (normal for first run)")

    dependency_graph, _ = gds.graph.project.cypher(
        "dependency_analysis",
        """
        MATCH (n)
        WHERE n:File OR n:ExternalDependency OR n:Component
        RETURN id(n) AS id,
               CASE
                 WHEN n:Component THEN 'Component'
                 WHEN n:ExternalDependency THEN 'ExternalDep'
                 ELSE 'File'
               END AS nodeType,
               COALESCE(n.name, n.path, n.import_path) AS name
        """,
        """
        MATCH (source)-[r:DEPENDS_ON|RESOLVED_TO]->(target)
        RETURN id(source) AS source, id(target) AS target,
               type(r) AS relationshipType
        """
    )

    print("Graph projection created with:")
    print(f"  Nodes: {dependency_graph.node_count()}")
    print(f"  Relationships: {dependency_graph.relationship_count()}")
    print()

    # Run PageRank to find most influential components
    print("Running PageRank analysis...")
    pagerank_result = gds.pageRank.stream(dependency_graph)
    top_components = pagerank_result.nlargest(10, 'score')

    print("🏆 Most Influential Components:")
    for _, row in top_components.iterrows():
        print(f"   Score: {row['score']:.4f} - Node ID: {row['nodeId']}")
    print()

    # Run Louvain community detection
    print("Running community detection...")
    louvain_result = gds.louvain.stream(dependency_graph)
    communities = louvain_result.groupby('communityId').size().sort_values(ascending=False)

    print("🏘️  Dependency Communities:")
    for community_id, size in communities.head(5).items():
        print(f"   Community {community_id}: {size} nodes")
    print()

    # Clean up
    dependency_graph.drop()


def demo_hybrid_queries(session):
    """Demonstrate hybrid queries combining multiple access patterns."""
    print("\n🔄 5. HYBRID QUERIES: Combining Multiple Access Patterns")
    print("=" * 60)

    # Complex query combining traversal, centrality, and text search
    query = """
    // Find high-risk vulnerabilities using multiple signals
    MATCH (cve:CVE)-[:AFFECTS]->(vuln_comp:Component)
    WHERE cve.cvss_score >= 7.0  // High severity only

    // Graph traversal: Find dependency paths to public APIs
    OPTIONAL MATCH path = (api_file:File)-[:DEPENDS_ON*1..3]->(ed:ExternalDependency)-[:RESOLVED_TO]->(vuln_comp)
    WHERE api_file.package CONTAINS "api"
       OR api_file.package CONTAINS "controller"

    WITH cve, vuln_comp,
         count(DISTINCT path) AS api_exposure_count,
         min(length(path)) AS shortest_path_to_api

    // Component similarity: Check if similar components exist
    OPTIONAL MATCH (similar:Component)
    WHERE similar <> vuln_comp
      AND similar.embedding IS NOT NULL
      AND vuln_comp.embedding IS NOT NULL
      AND gds.similarity.cosine(similar.embedding, vuln_comp.embedding) > 0.8

    WITH cve, vuln_comp, api_exposure_count, shortest_path_to_api,
         count(DISTINCT similar) AS similar_component_count

    // Calculate composite risk score
    WITH cve, vuln_comp,
         api_exposure_count,
         shortest_path_to_api,
         similar_component_count,
         // Risk formula combining multiple factors
         (cve.cvss_score *
          CASE WHEN api_exposure_count > 0 THEN 2.0 ELSE 1.0 END *
          CASE WHEN shortest_path_to_api <= 2 THEN 1.5 ELSE 1.0 END *
          (1 + similar_component_count * 0.2)
         ) AS composite_risk_score

    // Text search: Check for known attack patterns
    WITH cve, vuln_comp, api_exposure_count, shortest_path_to_api,
         similar_component_count, composite_risk_score,
         CASE
           WHEN toLower(cve.description) CONTAINS "remote code execution" THEN true
           WHEN toLower(cve.description) CONTAINS "sql injection" THEN true
           WHEN toLower(cve.description) CONTAINS "authentication bypass" THEN true
           ELSE false
         END AS has_critical_keywords

    WHERE api_exposure_count > 0 OR composite_risk_score > 15.0

    RETURN cve.cve_id AS vulnerability,
           vuln_comp.name AS component,
           round(cve.cvss_score, 1) AS cvss_score,
           api_exposure_count AS api_exposures,
           shortest_path_to_api AS min_path_length,
           similar_component_count AS similar_components,
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
        print(f"  Component: {record['component']}")
        print(f"  CVSS Score: {record['cvss_score']}")
        print(f"  API Exposures: {record['api_exposures']}")
        print(f"  Min Path to API: {record['min_path_length']} hops")
        print(f"  Similar Components: {record['similar_components']}")
        print(f"  Composite Risk: {record['risk_score']}")
        print(f"  Critical Pattern: {record['critical_attack_pattern']}")
        print("-" * 40)


def main():
    """Run all CVE analysis demonstrations."""
    print("🛡️  CVE ANALYSIS DEMO - Multi-Modal Neo4j Access Patterns")
    print("=" * 70)
    print()

    # Connect to Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    gds = GraphDataScience(NEO4J_URI, auth=(
        NEO4J_USERNAME, NEO4J_PASSWORD), database=NEO4J_DATABASE)

    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            # Check if we have data
            count_check = session.run("MATCH (cve:CVE) RETURN count(cve) AS cve_count").single()
            if count_check["cve_count"] == 0:
                print("❌ No CVE data found. Please run: python cve_analysis.py first")
                return

            print(f"✅ Found {count_check['cve_count']} CVEs in database")
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
            print("• Vector search finds similar vulnerable components")
            print("• Lucene search identifies related vulnerability patterns")
            print("• Graph algorithms highlight critical architectural components")
            print("• Hybrid queries combine multiple signals for comprehensive risk assessment")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
