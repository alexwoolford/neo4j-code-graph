#!/usr/bin/env python3
"""
General-Purpose CVE Impact Analysis

This tool analyzes CVE impact for ANY codebase by:
1. Dynamically extracting dependencies from the Neo4j code graph
2. Fetching relevant CVEs from the National Vulnerability Database
3. Creating a comprehensive vulnerability impact graph
4. Providing multi-modal analysis capabilities

NO HARDCODED MAPPINGS - Works with any language, any dependencies, any codebase.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
from datetime import datetime

# Add project root to path
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common import setup_logging, create_neo4j_driver
from utils import get_neo4j_config
from cve_cache_manager import UniversalCVEManager

logger = logging.getLogger(__name__)


class UniversalCVEAnalyzer:
    """Language-agnostic CVE analyzer that works with any codebase."""
    
    def __init__(self, driver, database: str = "neo4j"):
        self.driver = driver
        self.database = database
        self.cve_manager = UniversalCVEManager()
    
    def extract_codebase_dependencies(self) -> Dict[str, Set[str]]:
        """Extract all dependencies from any codebase in the graph."""
        logger.info("🔍 Extracting dependencies from codebase...")
        
        with self.driver.session(database=self.database) as session:
            # Get all external dependencies regardless of language
            query = """
            MATCH (ed:ExternalDependency)
            RETURN DISTINCT ed.import_path AS dependency_path,
                   ed.language AS language,
                   ed.ecosystem AS ecosystem
            ORDER BY dependency_path
            """
            
            result = session.run(query)
            dependencies_by_ecosystem = {}
            
            for record in result:
                dep_path = record["dependency_path"]
                language = record.get("language", "unknown")
                ecosystem = record.get("ecosystem", "unknown")
                
                # Group by ecosystem for targeted CVE searching
                key = f"{language}:{ecosystem}" if language != "unknown" else "unknown"
                if key not in dependencies_by_ecosystem:
                    dependencies_by_ecosystem[key] = set()
                
                dependencies_by_ecosystem[key].add(dep_path)
            
            # Also extract from file analysis for languages without explicit dependency tracking
            query = """
            MATCH (f:File)
            WHERE f.path =~ '.*\\.(py|js|ts|go|rs|cpp|c|h|java|cs|php|rb)$'
            RETURN DISTINCT f.path AS file_path,
                   f.language AS language
            LIMIT 1000
            """
            
            result = session.run(query)
            file_languages = set()
            for record in result:
                if record["language"]:
                    file_languages.add(record["language"].lower())
            
            logger.info(f"📊 Found dependencies in {len(dependencies_by_ecosystem)} ecosystems")
            logger.info(f"📊 Detected languages: {file_languages}")
            
            return dependencies_by_ecosystem, file_languages
    
    def create_universal_component_search_terms(self, dependencies: Dict[str, Set[str]]) -> Set[str]:
        """Create language-agnostic search terms from any dependency structure."""
        search_terms = set()
        
        for ecosystem, deps in dependencies.items():
            for dep in deps:
                # Universal patterns that work across languages
                search_terms.add(dep.lower())
                
                # Extract meaningful parts from different naming conventions
                parts = []
                
                # Java/C#: com.vendor.product or org.vendor.product  
                if '.' in dep:
                    parts.extend(dep.split('.'))
                
                # Python/Node: vendor-product or vendor_product
                if '-' in dep:
                    parts.extend(dep.split('-'))
                if '_' in dep:
                    parts.extend(dep.split('_'))
                
                # Go: github.com/vendor/product
                if '/' in dep:
                    parts.extend(dep.split('/'))
                
                # Rust: vendor::product
                if '::' in dep:
                    parts.extend(dep.split('::'))
                
                # Add meaningful parts (filter out common prefixes)
                for part in parts:
                    if part and len(part) > 2 and part not in ['com', 'org', 'net', 'io', 'www', 'github']:
                        search_terms.add(part.lower())
        
        logger.info(f"🎯 Generated {len(search_terms)} universal search terms")
        return search_terms
    
    def fetch_relevant_cves(self, search_terms: Set[str], api_key: Optional[str] = None) -> List[Dict]:
        """Fetch CVEs relevant to the extracted dependencies."""
        logger.info("🌐 Fetching relevant CVEs from National Vulnerability Database...")
        
        return self.cve_manager.fetch_targeted_cves(
            api_key=api_key,
            search_terms=search_terms,
            max_results=2000,  # Reasonable limit for comprehensive analysis
            days_back=365      # One year of CVE data
        )
    
    def create_vulnerability_graph(self, cve_data: List[Dict]) -> int:
        """Create CVE and vulnerability nodes in Neo4j."""
        logger.info("📊 Creating vulnerability graph...")
        
        if not cve_data:
            logger.warning("No CVE data to process")
            return 0
        
        with self.driver.session(database=self.database) as session:
            # Create CVE nodes
            cve_nodes = []
            for cve_entry in cve_data:
                cve = cve_entry.get("cve", {})
                
                # Extract basic CVE information
                cve_id = cve.get("id", "")
                descriptions = cve.get("descriptions", [])
                description = ""
                for desc in descriptions:
                    if desc.get("lang") == "en":
                        description = desc.get("value", "")
                        break
                
                # Extract CVSS score
                metrics = cve.get("metrics", {})
                cvss_score = 0.0
                cvss_vector = ""
                
                if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
                    cvss_data = metrics["cvssMetricV31"][0]["cvssData"]
                    cvss_score = cvss_data.get("baseScore", 0.0)
                    cvss_vector = cvss_data.get("vectorString", "")
                elif "cvssMetricV30" in metrics and metrics["cvssMetricV30"]:
                    cvss_data = metrics["cvssMetricV30"][0]["cvssData"]
                    cvss_score = cvss_data.get("baseScore", 0.0)
                    cvss_vector = cvss_data.get("vectorString", "")
                
                # Extract publication date
                published = cve.get("published", "")
                
                cve_nodes.append({
                    "cve_id": cve_id,
                    "description": description,
                    "cvss_score": cvss_score,
                    "cvss_vector": cvss_vector,
                    "published": published,
                    "severity": self._get_severity(cvss_score)
                })
            
            # Bulk create CVE nodes
            if cve_nodes:
                create_query = """
                UNWIND $cve_nodes AS cve
                MERGE (c:CVE {cve_id: cve.cve_id})
                SET c.description = cve.description,
                    c.cvss_score = cve.cvss_score,
                    c.cvss_vector = cve.cvss_vector,
                    c.published = cve.published,
                    c.severity = cve.severity,
                    c.updated_at = datetime()
                """
                session.run(create_query, cve_nodes=cve_nodes)
                logger.info(f"✅ Created {len(cve_nodes)} CVE nodes")
            
            # Link CVEs to dependencies based on content matching
            self._link_cves_to_dependencies(session, cve_data)
            
            return len(cve_nodes)
    
    def _get_severity(self, cvss_score: float) -> str:
        """Get severity level from CVSS score."""
        if cvss_score >= 9.0:
            return "CRITICAL"
        elif cvss_score >= 7.0:
            return "HIGH"
        elif cvss_score >= 4.0:
            return "MEDIUM"
        elif cvss_score > 0.0:
            return "LOW"
        else:
            return "NONE"
    
    def _link_cves_to_dependencies(self, session, cve_data: List[Dict]):
        """Link CVEs to external dependencies based on content analysis."""
        logger.info("🔗 Linking CVEs to codebase dependencies...")
        
        # Get all external dependencies
        deps_query = """
        MATCH (ed:ExternalDependency)
        RETURN ed.import_path AS import_path, id(ed) AS dep_id
        """
        deps_result = session.run(deps_query)
        dependencies = {record["import_path"]: record["dep_id"] for record in deps_result}
        
        if not dependencies:
            logger.warning("No external dependencies found in graph")
            return
        
        # Create links based on content matching
        links = []
        for cve_entry in cve_data:
            cve = cve_entry.get("cve", {})
            cve_id = cve.get("id", "")
            
            # Extract all text content for matching
            description = ""
            descriptions = cve.get("descriptions", [])
            for desc in descriptions:
                if desc.get("lang") == "en":
                    description = desc.get("value", "").lower()
                    break
            
            # Extract CPE information
            cpe_components = set()
            configurations = cve.get("configurations", [])
            for config in configurations:
                for node in config.get("nodes", []):
                    for cpe_match in node.get("cpeMatch", []):
                        cpe = cpe_match.get("criteria", "")
                        if cpe.startswith("cpe:2.3:"):
                            parts = cpe.split(":")
                            if len(parts) >= 6:
                                vendor = parts[3].lower()
                                product = parts[4].lower()
                                cpe_components.add(vendor)
                                cpe_components.add(product)
                                cpe_components.add(f"{vendor}:{product}")
            
            # Match against dependencies
            all_cve_text = f"{description} {' '.join(cpe_components)}"
            
            for dep_path, dep_id in dependencies.items():
                if self._is_dependency_affected(dep_path, all_cve_text, cpe_components):
                    links.append({
                        "cve_id": cve_id,
                        "dep_id": dep_id,
                        "confidence": self._calculate_match_confidence(dep_path, all_cve_text, cpe_components)
                    })
        
        # Create relationships
        if links:
            link_query = """
            UNWIND $links AS link
            MATCH (cve:CVE {cve_id: link.cve_id})
            MATCH (ed:ExternalDependency) WHERE id(ed) = link.dep_id
            MERGE (cve)-[r:AFFECTS]->(ed)
            SET r.confidence = link.confidence,
                r.created_at = datetime()
            """
            session.run(link_query, links=links)
            logger.info(f"🔗 Created {len(links)} CVE-dependency relationships")
    
    def _is_dependency_affected(self, dep_path: str, cve_text: str, cpe_components: Set[str]) -> bool:
        """Determine if a dependency is affected by a CVE using universal matching."""
        dep_lower = dep_path.lower()
        
        # Direct text match
        if dep_lower in cve_text:
            return True
        
        # Extract components from dependency path
        dep_parts = set()
        
        # Split by various separators
        for sep in ['.', '/', '-', '_', '::']:
            if sep in dep_path:
                dep_parts.update(part.lower() for part in dep_path.split(sep) if len(part) > 2)
        
        # Check if any part matches CPE components
        if dep_parts.intersection(cpe_components):
            return True
        
        # Check for partial matches in CVE text
        for part in dep_parts:
            if len(part) > 3 and part in cve_text:
                return True
        
        return False
    
    def _calculate_match_confidence(self, dep_path: str, cve_text: str, cpe_components: Set[str]) -> float:
        """Calculate confidence score for CVE-dependency matching."""
        confidence = 0.0
        dep_lower = dep_path.lower()
        
        # Direct path match (highest confidence)
        if dep_lower in cve_text:
            confidence += 0.8
        
        # CPE component matches
        dep_parts = set()
        for sep in ['.', '/', '-', '_', '::']:
            if sep in dep_path:
                dep_parts.update(part.lower() for part in dep_path.split(sep) if len(part) > 2)
        
        matches = dep_parts.intersection(cpe_components)
        if matches:
            confidence += 0.6 * (len(matches) / len(dep_parts))
        
        # Partial text matches
        partial_matches = sum(1 for part in dep_parts if len(part) > 3 and part in cve_text)
        if partial_matches:
            confidence += 0.4 * (partial_matches / len(dep_parts))
        
        return min(confidence, 1.0)
    
    def setup_indexes(self):
        """Create necessary indexes for efficient querying."""
        logger.info("📊 Setting up indexes for CVE analysis...")
        
        with self.driver.session(database=self.database) as session:
            indexes = [
                # CVE indexes
                "CREATE INDEX cve_cvss_score IF NOT EXISTS FOR (cve:CVE) ON (cve.cvss_score)",
                "CREATE INDEX cve_severity IF NOT EXISTS FOR (cve:CVE) ON (cve.severity)",
                "CREATE INDEX cve_published IF NOT EXISTS FOR (cve:CVE) ON (cve.published)",
                
                # Full-text index for CVE descriptions
                "CREATE FULLTEXT INDEX cve_description_index IF NOT EXISTS FOR (cve:CVE) ON EACH [cve.description]",
            ]
            
            for index_query in indexes:
                try:
                    session.run(index_query)
                    logger.debug(f"✅ Created index: {index_query}")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        logger.debug(f"Index already exists: {index_query}")
                    else:
                        logger.warning(f"Failed to create index: {e}")
    
    def analyze_vulnerability_impact(self, max_hops: int = 4, risk_threshold: float = 7.0):
        """Analyze vulnerability impact using multi-modal Neo4j analysis."""
        logger.info("🎯 Analyzing vulnerability impact...")
        
        with self.driver.session(database=self.database) as session:
            # Find high-risk vulnerabilities with dependency paths
            analysis_query = """
            MATCH (cve:CVE)-[:AFFECTS]->(ed:ExternalDependency)
            WHERE cve.cvss_score >= $risk_threshold
            
            // Find dependency paths to source files
            OPTIONAL MATCH path = (f:File)-[:DEPENDS_ON*1..$max_hops]->(ed)
            
            WITH cve, ed, collect(DISTINCT f) AS affected_files,
                 count(DISTINCT f) AS file_count,
                 min(length(path)) AS shortest_path
            
            // Calculate impact score
            WITH cve, ed, affected_files, file_count, shortest_path,
                 (cve.cvss_score * file_count / COALESCE(shortest_path, 10)) AS impact_score
            
            RETURN cve.cve_id AS vulnerability,
                   cve.description AS description,
                   cve.cvss_score AS cvss_score,
                   cve.severity AS severity,
                   ed.import_path AS affected_dependency,
                   file_count AS affected_file_count,
                   shortest_path AS dependency_distance,
                   round(impact_score, 2) AS calculated_impact
            ORDER BY impact_score DESC
            LIMIT 20
            """
            
            result = session.run(analysis_query, 
                               risk_threshold=risk_threshold, 
                               max_hops=max_hops)
            
            vulnerabilities = []
            for record in result:
                vulnerabilities.append({
                    "vulnerability": record["vulnerability"],
                    "description": record["description"][:100] + "..." if len(record["description"]) > 100 else record["description"],
                    "cvss_score": record["cvss_score"],
                    "severity": record["severity"],
                    "affected_dependency": record["affected_dependency"],
                    "affected_file_count": record["affected_file_count"],
                    "dependency_distance": record["dependency_distance"],
                    "calculated_impact": record["calculated_impact"]
                })
            
            return vulnerabilities
    
    def generate_impact_report(self, vulnerabilities: List[Dict]):
        """Generate a comprehensive vulnerability impact report."""
        if not vulnerabilities:
            print("\n✅ No high-risk vulnerabilities found in your codebase!")
            return
        
        print(f"\n🚨 VULNERABILITY IMPACT ANALYSIS")
        print("=" * 70)
        print(f"Found {len(vulnerabilities)} high-risk vulnerabilities affecting your codebase")
        print()
        
        # Summary by severity
        severity_counts = {}
        for vuln in vulnerabilities:
            severity = vuln["severity"]
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        print("📊 Severity Distribution:")
        for severity, count in sorted(severity_counts.items()):
            print(f"   {severity}: {count} vulnerabilities")
        print()
        
        # Top vulnerabilities
        print("🎯 Top Vulnerabilities by Impact:")
        print("-" * 70)
        
        for i, vuln in enumerate(vulnerabilities[:10], 1):
            print(f"{i:2d}. {vuln['vulnerability']} ({vuln['severity']})")
            print(f"    CVSS: {vuln['cvss_score']} | Impact: {vuln['calculated_impact']}")
            print(f"    Dependency: {vuln['affected_dependency']}")
            print(f"    Affects {vuln['affected_file_count']} files via {vuln['dependency_distance']} hops")
            print(f"    {vuln['description']}")
            print()
        
        print("💡 Next Steps:")
        print("   1. Review dependencies with highest impact scores")
        print("   2. Check for available security updates")
        print("   3. Consider alternative dependencies for critical vulnerabilities")
        print("   4. Implement additional security controls for affected components")


def main():
    """Main function for universal CVE analysis."""
    parser = argparse.ArgumentParser(
        description="Universal CVE Impact Analysis - Works with ANY codebase"
    )
    
    parser.add_argument("--nvd-api-key", 
                       help="NVD API key for faster data retrieval (optional)")
    parser.add_argument("--risk-threshold", type=float, default=7.0,
                       help="Minimum CVSS score to consider (default: 7.0)")
    parser.add_argument("--max-hops", type=int, default=4,
                       help="Maximum dependency hops to analyze (default: 4)")
    parser.add_argument("--database", default="neo4j",
                       help="Neo4j database name (default: neo4j)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level)
    
    # Get NVD API key from environment if not provided
    api_key = args.nvd_api_key or os.getenv("NVD_API_KEY")
    if not api_key:
        logger.warning("🔑 No NVD API key provided - analysis will be slower")
        logger.info("💡 Get a free API key at: https://nvd.nist.gov/developers/request-an-api-key")
        logger.info("💡 Set it with: export NVD_API_KEY=your_key_here")
    else:
        logger.info("🔑 Using NVD API key for analysis")
    
    # Connect to Neo4j
    config = get_neo4j_config()
    driver = create_neo4j_driver(config[0], config[1], config[2])
    
    try:
        # Initialize analyzer
        analyzer = UniversalCVEAnalyzer(driver, args.database)
        
        # Setup indexes
        analyzer.setup_indexes()
        
        # Extract dependencies from codebase
        dependencies, languages = analyzer.extract_codebase_dependencies()
        
        if not dependencies:
            logger.error("❌ No dependencies found in codebase")
            logger.info("💡 Make sure you've run the code analysis first:")
            logger.info("💡 ./run_pipeline.sh <your-repo-url>")
            return
        
        logger.info(f"📊 Detected {sum(len(deps) for deps in dependencies.values())} dependencies")
        logger.info(f"📊 Languages: {', '.join(languages)}")
        
        # Generate universal search terms
        search_terms = analyzer.create_universal_component_search_terms(dependencies)
        
        # Fetch relevant CVEs
        cve_data = analyzer.fetch_relevant_cves(search_terms, api_key)
        
        if not cve_data:
            logger.warning("⚠️  No relevant CVEs found")
            return
        
        # Create vulnerability graph
        cve_count = analyzer.create_vulnerability_graph(cve_data)
        logger.info(f"📊 Processed {cve_count} CVEs")
        
        # Analyze impact
        vulnerabilities = analyzer.analyze_vulnerability_impact(
            max_hops=args.max_hops,
            risk_threshold=args.risk_threshold
        )
        
        # Generate report
        analyzer.generate_impact_report(vulnerabilities)
        
        print(f"\n✅ Universal CVE analysis complete!")
        print(f"📊 Analyzed {cve_count} CVEs across {len(languages)} languages")
        print(f"🎯 Multi-modal Neo4j analysis available via Cypher queries")
        
    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
    finally:
        driver.close()


if __name__ == "__main__":
    main()
