#!/usr/bin/env python3
"""
Centrality Analysis for Code Graph - Identify Important Code Elements

This script implements the centrality analysis outlined in the enhancement plan:
- PageRank: Find methods that are central in the call ecosystem
- Betweenness Centrality: Identify bottlenecks and critical connectors
- Degree Centrality: Find hub methods (high out-degree) and authority methods (high in-degree)
- HITS: Distinguish between hubs (orchestrators) and authorities (utilities)

Based on Neo4j Graph Data Science algorithms to highlight structurally important code.
"""

import argparse
import logging
from time import perf_counter

from graphdatascience import GraphDataScience

try:
    # Try absolute import when called from CLI wrapper
    from utils.common import setup_logging, create_neo4j_driver, add_common_args
except ImportError:
    # Fallback to relative import when used as module
    from ..utils.common import setup_logging, create_neo4j_driver, add_common_args

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Compute centrality measures to identify important code elements"
    )
    add_common_args(parser)
    parser.add_argument(
        "--algorithms",
        nargs="+",
        choices=["pagerank", "betweenness", "degree", "hits"],
        default=["pagerank", "betweenness", "degree"],
        help="Centrality algorithms to run",
    )
    parser.add_argument(
        "--min-methods",
        type=int,
        default=100,
        help="Minimum number of methods required to run analysis",
    )
    parser.add_argument(
        "--top-n", type=int, default=20, help="Number of top results to display for each algorithm"
    )
    parser.add_argument(
        "--write-back",
        action="store_true",
        help="Write centrality scores back to Method nodes as properties",
    )
    return parser.parse_args()


def check_call_graph_exists(gds):
    """Check if we have method calls to analyze."""
    query = """
    MATCH ()-[r:CALLS]->()
    RETURN count(r) as call_count
    """
    result = gds.run_cypher(query)
    call_count = result.iloc[0]["call_count"]

    query = """
    MATCH (m:Method)
    RETURN count(m) as method_count
    """
    result = gds.run_cypher(query)
    method_count = result.iloc[0]["method_count"]

    return call_count, method_count


def create_call_graph_projection(gds, graph_name="method_call_graph"):
    """Create or recreate the call graph projection for analysis."""

    # Drop existing projection if it exists
    try:
        gds.graph.drop(graph_name)
        logger.info(f"Dropped existing graph projection: {graph_name}")
    except Exception as e:
        pass  # Graph doesn't exist, which is fine

    # Create new projection
    logger.info("Creating method call graph projection...")
    start_time = perf_counter()

    G, result = gds.graph.project(
        graph_name, ["Method"], {"CALLS": {"orientation": "NATURAL"}}  # Directed graph
    )

    creation_time = perf_counter() - start_time

    logger.info(f"Graph projection created in {creation_time:.2f}s")
    logger.info(f"  Nodes: {result['nodeCount']:,}")
    logger.info(f"  Relationships: {result['relationshipCount']:,}")

    return G


def run_pagerank_analysis(gds, graph, top_n=20, write_back=False):
    """Run PageRank to find methods central in the call ecosystem."""
    logger.info("🔍 Running PageRank analysis...")
    start_time = perf_counter()

    if write_back:
        result = gds.pageRank.write(
            graph, writeProperty="pagerank_score", maxIterations=20, dampingFactor=0.85
        )

        # Get top results
        query = """
        MATCH (m:Method)
        WHERE m.pagerank_score IS NOT NULL
        RETURN m.name as method_name,
               m.class as class_name,
               m.file as file,
               m.pagerank_score as score
        ORDER BY m.pagerank_score DESC
        LIMIT $top_n
        """
        top_results = gds.run_cypher(query, {"top_n": top_n})

    else:
        result = gds.pageRank.stream(graph, maxIterations=20, dampingFactor=0.85).head(top_n)

        # Enrich with method details
        if not result.empty:
            method_ids = result["nodeId"].tolist()
            query = """
            UNWIND $nodeIds as nodeId
            MATCH (m:Method) WHERE id(m) = nodeId
            RETURN id(m) as nodeId, m.name as method_name,
                   m.class as class_name, m.file as file
            """
            method_details = gds.run_cypher(query, {"nodeIds": method_ids})
            top_results = result.merge(method_details, on="nodeId")

    analysis_time = perf_counter() - start_time

    logger.info(f"PageRank completed in {analysis_time:.2f}s")
    logger.info(
        f"Centrality range: {result.get('centralityDistribution', {}).get('min', 'N/A')} - {result.get('centralityDistribution', {}).get('max', 'N/A')}"
    )

    print("\n🏆 TOP PAGE RANK METHODS (Most Central in Call Ecosystem):")
    print("-" * 80)
    if "score" in top_results.columns:
        for _, row in top_results.iterrows():
            class_name = row["class_name"] if row["class_name"] else "Unknown"
            print(f"  {row['score']:.6f} | {class_name}.{row['method_name']} ({row['file']})")
    else:
        for _, row in top_results.iterrows():
            class_name = row["class_name"] if row["class_name"] else "Unknown"
            print(f"  {row['score']:.6f} | {class_name}.{row['method_name']} ({row['file']})")

    return top_results


def run_betweenness_analysis(gds, graph, top_n=20, write_back=False):
    """Run Betweenness Centrality to find critical connectors and bottlenecks."""
    logger.info("🔍 Running Betweenness Centrality analysis...")
    start_time = perf_counter()

    if write_back:
        result = gds.betweenness.write(graph, writeProperty="betweenness_score")

        query = """
        MATCH (m:Method)
        WHERE m.betweenness_score IS NOT NULL
        RETURN m.name as method_name,
               m.class as class_name,
               m.file as file,
               m.betweenness_score as score
        ORDER BY m.betweenness_score DESC
        LIMIT $top_n
        """
        top_results = gds.run_cypher(query, {"top_n": top_n})

    else:
        result = gds.betweenness.stream(graph).head(top_n)

        if not result.empty:
            method_ids = result["nodeId"].tolist()
            query = """
            UNWIND $nodeIds as nodeId
            MATCH (m:Method) WHERE id(m) = nodeId
            RETURN id(m) as nodeId, m.name as method_name,
                   m.class as class_name, m.file as file
            """
            method_details = gds.run_cypher(query, {"nodeIds": method_ids})
            top_results = result.merge(method_details, on="nodeId")

    analysis_time = perf_counter() - start_time

    logger.info(f"Betweenness completed in {analysis_time:.2f}s")

    print("\n🌉 TOP BETWEENNESS METHODS (Critical Connectors & Bottlenecks):")
    print("-" * 80)
    if "score" in top_results.columns:
        for _, row in top_results.iterrows():
            class_name = row["class_name"] if row["class_name"] else "Unknown"
            print(f"  {row['score']:.6f} | {class_name}.{row['method_name']} ({row['file']})")
    else:
        for _, row in top_results.iterrows():
            class_name = row["class_name"] if row["class_name"] else "Unknown"
            print(f"  {row['score']:.6f} | {class_name}.{row['method_name']} ({row['file']})")

    return top_results


def run_degree_analysis(gds, graph, top_n=20, write_back=False):
    """Run Degree Centrality to find hub methods and authority methods."""
    logger.info("🔍 Running Degree Centrality analysis...")
    start_time = perf_counter()

    # Get both in-degree and out-degree
    query = """
    MATCH (m:Method)
    OPTIONAL MATCH (m)-[out:CALLS]->()
    OPTIONAL MATCH ()-[in:CALLS]->(m)
    WITH m, count(DISTINCT out) as out_degree, count(DISTINCT in) as in_degree
    RETURN id(m) as nodeId, m.name as method_name, m.class as class_name,
           m.file as file, out_degree, in_degree,
           (out_degree + in_degree) as total_degree
    ORDER BY total_degree DESC
    LIMIT $top_n
    """

    result = gds.run_cypher(query, {"top_n": top_n})

    if write_back:
        # Write degree scores back to nodes
        write_query = """
        MATCH (m:Method)
        OPTIONAL MATCH (m)-[out:CALLS]->()
        OPTIONAL MATCH ()-[in:CALLS]->(m)
        WITH m, count(DISTINCT out) as out_degree, count(DISTINCT in) as in_degree
        SET m.out_degree = out_degree, m.in_degree = in_degree,
            m.total_degree = out_degree + in_degree
        """
        gds.run_cypher(write_query)
        logger.info("Degree scores written back to Method nodes")

    analysis_time = perf_counter() - start_time
    logger.info(f"Degree analysis completed in {analysis_time:.2f}s")

    print("\n📊 TOP DEGREE METHODS (Hubs & Authorities):")
    print("-" * 80)
    print("  Total | In  | Out | Method")
    print("-" * 80)

    for _, row in result.iterrows():
        class_name = row["class_name"] if row["class_name"] else "Unknown"
        print(
            f"  {row['total_degree']:5d} | {row['in_degree']:3d} | {row['out_degree']:3d} | {class_name}.{row['method_name']} ({row['file']})"
        )

    return result


def run_hits_analysis(gds, graph, top_n=20, write_back=False):
    """Run HITS algorithm to distinguish hubs (orchestrators) vs authorities (utilities)."""
    logger.info("🔍 Running HITS analysis...")
    start_time = perf_counter()

    # Note: Check if HITS is available in your GDS version
    try:
        if write_back:
            result = gds.alpha.hits.write(graph, writeProperty="hits", hitsIterations=20)

            query = """
            MATCH (m:Method)
            WHERE m.hits_auth IS NOT NULL
            RETURN m.name as method_name, m.class as class_name, m.file as file,
                   m.hits_auth as authority_score, m.hits_hub as hub_score
            ORDER BY m.hits_auth DESC
            LIMIT $top_n
            """
            authorities = gds.run_cypher(query, {"top_n": top_n})

            query = """
            MATCH (m:Method)
            WHERE m.hits_hub IS NOT NULL
            RETURN m.name as method_name, m.class as class_name, m.file as file,
                   m.hits_auth as authority_score, m.hits_hub as hub_score
            ORDER BY m.hits_hub DESC
            LIMIT $top_n
            """
            hubs = gds.run_cypher(query, {"top_n": top_n})

        else:
            result = gds.alpha.hits.stream(graph, hitsIterations=20)

            # Get top authorities
            authorities = result.nlargest(top_n, "auth")
            hubs = result.nlargest(top_n, "hub")

            # Enrich with method details
            if not authorities.empty:
                auth_ids = authorities["nodeId"].tolist()
                query = """
                UNWIND $nodeIds as nodeId
                MATCH (m:Method) WHERE id(m) = nodeId
                RETURN id(m) as nodeId, m.name as method_name,
                       m.class as class_name, m.file as file
                """
                auth_details = gds.run_cypher(query, {"nodeIds": auth_ids})
                authorities = authorities.merge(auth_details, on="nodeId")

            if not hubs.empty:
                hub_ids = hubs["nodeId"].tolist()
                hub_details = gds.run_cypher(query, {"nodeIds": hub_ids})
                hubs = hubs.merge(hub_details, on="nodeId")

        analysis_time = perf_counter() - start_time
        logger.info(f"HITS completed in {analysis_time:.2f}s")

        print("\n🎯 TOP AUTHORITY METHODS (Called by Many - Utilities):")
        print("-" * 80)
        auth_col = "authority_score" if "authority_score" in authorities.columns else "auth"
        for _, row in authorities.iterrows():
            class_name = row["class_name"] if row["class_name"] else "Unknown"
            print(f"  {row[auth_col]:.6f} | {class_name}.{row['method_name']} ({row['file']})")

        print("\n🎯 TOP HUB METHODS (Call Many Others - Orchestrators):")
        print("-" * 80)
        hub_col = "hub_score" if "hub_score" in hubs.columns else "hub"
        for _, row in hubs.iterrows():
            class_name = row["class_name"] if row["class_name"] else "Unknown"
            print(f"  {row[hub_col]:.6f} | {class_name}.{row['method_name']} ({row['file']})")

        return authorities, hubs

    except Exception as e:
        logger.warning(f"HITS algorithm not available or failed: {e}")
        logger.warning("This may require a newer version of Neo4j GDS")
        return None, None


def summarize_analysis(
    pagerank_results, betweenness_results, degree_results, hits_authorities=None, hits_hubs=None
):
    """Provide a summary of key findings from centrality analysis."""
    print("\n" + "=" * 80)
    print("📊 CENTRALITY ANALYSIS SUMMARY")
    print("=" * 80)

    if pagerank_results is not None and not pagerank_results.empty:
        top_pagerank = pagerank_results.iloc[0]
        class_name = top_pagerank["class_name"] if top_pagerank["class_name"] else "Unknown"
        print(f"🏆 Most Central Method (PageRank): {class_name}.{top_pagerank['method_name']}")

    if betweenness_results is not None and not betweenness_results.empty:
        top_betweenness = betweenness_results.iloc[0]
        class_name = top_betweenness["class_name"] if top_betweenness["class_name"] else "Unknown"
        print(f"🌉 Critical Connector: {class_name}.{top_betweenness['method_name']}")

    if degree_results is not None and not degree_results.empty:
        top_degree = degree_results.iloc[0]
        class_name = top_degree["class_name"] if top_degree["class_name"] else "Unknown"
        print(
            f"📊 Highest Degree: {class_name}.{top_degree['method_name']} ({top_degree['total_degree']} connections)"
        )

    print("\n💡 Use these insights to:")
    print("  • Focus optimization efforts on high PageRank methods")
    print("  • Review high betweenness methods for architectural bottlenecks")
    print("  • Consider refactoring high-degree methods if they're doing too much")
    print("  • Protect critical connector methods with extra testing")


def main():
    """Main analysis function."""
    args = parse_args()

    setup_logging(args.log_level, args.log_file)
    driver = create_neo4j_driver(args.uri, args.username, args.password)

    try:
        # Initialize GDS
        gds = GraphDataScience(
            args.uri, auth=(args.username, args.password), database=args.database
        )
        logger.info(f"Connected to Neo4j GDS at {args.uri}")

        # Check if we have enough data
        call_count, method_count = check_call_graph_exists(gds)
        logger.info(f"Found {method_count:,} methods with {call_count:,} call relationships")

        if method_count < args.min_methods:
            logger.error(
                f"Insufficient methods for analysis. Found {method_count}, need at least {args.min_methods}"
            )
            return

        if call_count == 0:
            logger.error(
                "No CALLS relationships found. Run code_to_graph.py first to extract method calls."
            )
            return

        # Create graph projection
        graph = create_call_graph_projection(gds)

        # Run requested algorithms
        pagerank_results = None
        betweenness_results = None
        degree_results = None
        hits_authorities = None
        hits_hubs = None

        if "pagerank" in args.algorithms:
            pagerank_results = run_pagerank_analysis(gds, graph, args.top_n, args.write_back)

        if "betweenness" in args.algorithms:
            betweenness_results = run_betweenness_analysis(gds, graph, args.top_n, args.write_back)

        if "degree" in args.algorithms:
            degree_results = run_degree_analysis(gds, graph, args.top_n, args.write_back)

        if "hits" in args.algorithms:
            hits_authorities, hits_hubs = run_hits_analysis(gds, graph, args.top_n, args.write_back)

        # Provide summary
        summarize_analysis(
            pagerank_results, betweenness_results, degree_results, hits_authorities, hits_hubs
        )

        # Cleanup
        gds.graph.drop(graph.name())
        logger.info("Analysis completed successfully")

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise
    finally:
        driver.close()


if __name__ == "__main__":
    main()
