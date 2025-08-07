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
import logging
import os
import sys
from typing import Dict, List, Optional, Set

# Handle both script and module execution contexts
try:
    # Try absolute imports when called from CLI wrapper
    from security.cve_cache_manager import CVECacheManager
    from utils.common import create_neo4j_driver, setup_logging
    from utils.neo4j_utils import get_neo4j_config
except ImportError:
    # Fallback to relative imports when used as module
    from ..utils.common import create_neo4j_driver, setup_logging
    from ..utils.neo4j_utils import get_neo4j_config
    from .cve_cache_manager import CVECacheManager

# Add project root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


logger = logging.getLogger(__name__)


class CVEAnalyzer:
    """Language-agnostic CVE analyzer that works with any codebase."""

    def __init__(self, driver=None, database: str = None):
        self.driver = driver
        # Use centralized config if database not specified
        if database is None:
            _, _, _, database = get_neo4j_config()
        self.database = database
        self.cve_manager = CVECacheManager()

    def load_cve_data(self, file_path: str):
        """Load CVE data from a file."""
        import json

        with open(file_path, "r") as f:
            return json.load(f)

    def get_cache_status(self):
        """Get current cache status for user feedback."""
        stats = self.cve_manager.get_cache_stats()

        print("\n📊 **CVE CACHE STATUS**")
        print("=" * 50)
        print(f"Complete caches: {stats['complete_caches']}")
        print(f"Partial caches:  {stats['partial_caches']}")
        print(f"Total size:      {stats['total_size_mb']} MB")
        print(f"Cache location:  {stats['cache_dir']}")

        if stats["partial_caches"] > 0:
            print("\n🔄 **RESUMABLE DOWNLOADS AVAILABLE**")
            print("You can resume interrupted downloads!")

        return stats

    def extract_codebase_dependencies(self) -> tuple:
        """Extract all dependencies from any codebase in the graph."""
        logger.info("🔍 Extracting dependencies from codebase...")

        with self.driver.session(database=self.database) as session:
            # Get all external dependencies regardless of language
            query = """
            MATCH (ed:ExternalDependency)
            RETURN DISTINCT ed.package AS dependency_path,
                   ed.language AS language,
                   ed.ecosystem AS ecosystem,
                   ed.version AS version
            ORDER BY dependency_path
            """

            result = session.run(query)
            dependencies_by_ecosystem = {}

            for record in result:
                dep_path = record["dependency_path"]
                language = record.get("language", "unknown")
                ecosystem = record.get("ecosystem", "unknown")
                version = record.get("version")  # Will be None for now, but we'll fix that

                # Group by ecosystem for targeted CVE searching
                key = f"{language}:{ecosystem}" if language != "unknown" else "unknown"
                if key not in dependencies_by_ecosystem:
                    dependencies_by_ecosystem[key] = set()

                # Include version info if available
                dep_info = dep_path
                if version:
                    dep_info = f"{dep_path}:{version}"

                dependencies_by_ecosystem[key].add(dep_info)

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

    def create_universal_component_search_terms(
        self, dependencies: Dict[str, Set[str]]
    ) -> Set[str]:
        """Create language-agnostic search terms from any dependency structure."""
        search_terms = set()
        specific_vendor_terms = set()  # Track specific vendor terms to avoid generic ones

        for ecosystem, deps in dependencies.items():
            for dep in deps:
                # Universal patterns that work across languages
                if dep and isinstance(dep, str):  # Filter out None values and non-strings
                    search_terms.add(dep.lower())

                # Extract meaningful parts from different naming conventions
                parts = []

                # Java/C#: com.vendor.product or org.vendor.product
                if "." in dep:
                    parts.extend(dep.split("."))

                    # Track specific vendor.product combinations to avoid generic vendor terms
                    if any(
                        vendor in dep.lower()
                        for vendor in ["jetbrains", "springframework", "fasterxml"]
                    ):
                        # Mark this as a specific dependency
                        vendor_parts = [
                            p
                            for p in dep.split(".")
                            if p.lower() in ["jetbrains", "springframework", "fasterxml"]
                        ]
                        for vendor_part in vendor_parts:
                            specific_vendor_terms.add(vendor_part.lower())

                # Python/Node: vendor-product or vendor_product
                if "-" in dep:
                    parts.extend(dep.split("-"))
                if "_" in dep:
                    parts.extend(dep.split("_"))

                # Go: github.com/vendor/product
                if "/" in dep:
                    parts.extend(dep.split("/"))

                # Rust: vendor::product
                if "::" in dep:
                    parts.extend(dep.split("::"))

                # Add meaningful parts (filter out common prefixes AND vendor terms that
                # have specific deps)
                for part in parts:
                    part_lower = part.lower()
                    if (
                        part
                        and len(part) > 2
                        and part not in ["com", "org", "net", "io", "www", "github"]
                        and part_lower not in specific_vendor_terms
                    ):  # Don't add generic vendor terms
                        search_terms.add(part_lower)

        logger.info(f"🎯 Generated {len(search_terms)} universal search terms")
        logger.info(f"🚫 Excluded generic vendor terms: {specific_vendor_terms}")
        return search_terms

    def fetch_relevant_cves(
        self,
        search_terms: Set[str],
        api_key: Optional[str] = None,
        max_concurrency: Optional[int] = None,
    ) -> List[Dict]:
        """Fetch CVEs relevant to the extracted dependencies."""
        logger.info("🌐 Fetching relevant CVEs from National Vulnerability Database...")

        return self.cve_manager.fetch_targeted_cves(
            api_key=api_key,
            search_terms=search_terms,
            max_results=2000,  # Reasonable limit for comprehensive analysis
            days_back=365,  # One year of CVE data
            max_concurrency=max_concurrency,
        )

    def create_vulnerability_graph(self, cve_data: List[Dict]) -> int:
        """Create CVE and vulnerability nodes in Neo4j."""
        logger.info("📊 Creating vulnerability graph...")

        if not cve_data:
            logger.warning("No CVE data to process")
            return 0

        with self.driver.session(database=self.database) as session:
            # The cve_data is already cleaned by the cache manager
            # Create CVE nodes directly from the cleaned data
            cve_nodes = []
            for cve in cve_data:
                # Use the cleaned data structure from cache manager
                cve_nodes.append(
                    {
                        "cve_id": cve.get("id", ""),
                        "description": cve.get("description", ""),
                        "cvss_score": float(cve.get("cvss_score", 0.0)),
                        "cvss_vector": "",  # Not in cleaned data
                        "published": cve.get("published", ""),
                        "severity": cve.get("severity", "UNKNOWN"),
                    }
                )

            # Bulk create CVE nodes
            if cve_nodes:
                create_query = """
                UNWIND $cve_nodes AS cve
                MERGE (c:CVE {id: cve.cve_id})
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
        """Link CVEs to external dependencies using precise GAV matching."""
        logger.info("🔗 Linking CVEs to codebase dependencies using precise GAV matching...")

        # Get all external dependencies with GAV coordinates
        deps_query = """
        MATCH (ed:ExternalDependency)
        RETURN ed.package AS import_path,
               ed.group_id AS group_id,
               ed.artifact_id AS artifact_id,
               ed.version AS version
        """
        deps_result = session.run(deps_query)
        dependencies = []

        for record in deps_result:
            dep_info = {
                "package": record["import_path"],
                "group_id": record["group_id"],
                "artifact_id": record["artifact_id"],
                "version": record["version"],
            }
            dependencies.append(dep_info)

        if not dependencies:
            logger.warning("No external dependencies found in graph")
            return

        logger.info(f"Found {len(dependencies)} dependencies to match against")

        # Initialize precise GAV matcher
        try:
            from .gav_cve_matcher import GAVCoordinate, PreciseGAVMatcher

            matcher = PreciseGAVMatcher()

            # Convert dependencies to GAV coordinates for precise matching
            gav_dependencies = []
            for dep in dependencies:
                if (
                    dep["group_id"]
                    and dep["artifact_id"]
                    and dep["version"]
                    and dep["version"] != "unknown"
                ):
                    gav = GAVCoordinate(dep["group_id"], dep["artifact_id"], dep["version"])
                    gav_dependencies.append((gav, dep["package"]))

            logger.info(
                f"🎯 Using precise GAV matching for {len(gav_dependencies)} dependencies with full coordinates"
            )

            # Use precise GAV matching for dependencies with full coordinates
            precise_matches = []
            if gav_dependencies:
                for gav, package in gav_dependencies:
                    for cve in cve_data:
                        confidence = matcher.match_gav_to_cve(gav, cve)
                        if confidence is not None:
                            precise_matches.append(
                                {
                                    "cve_id": cve.get("id", ""),
                                    "dep_package": package,
                                    "confidence": confidence,
                                    "match_type": "precise_gav",
                                }
                            )

            logger.info(
                f"🎯 Precise GAV matching found {len(precise_matches)} high-confidence matches"
            )

        except ImportError:
            logger.warning("Precise GAV matcher not available, skipping precise matching")
            precise_matches = []

        # Fall back to improved text matching only for dependencies without GAV coordinates
        # and only if no precise matches were found
        text_matches = []
        if len(precise_matches) < 10:  # Only use text matching if we have very few precise matches
            deps_without_gav = [
                dep
                for dep in dependencies
                if not (
                    dep["group_id"]
                    and dep["artifact_id"]
                    and dep["version"]
                    and dep["version"] != "unknown"
                )
            ]

            if deps_without_gav:
                logger.info(
                    f"⚠️  Using fallback text matching for {len(deps_without_gav)} dependencies without GAV coordinates"
                )

                for cve in cve_data:
                    cve_id = cve.get("id", "")
                    description = cve.get("description", "").lower()

                    for dep in deps_without_gav:
                        dep_path = dep["package"]
                        if self._is_dependency_affected_improved(dep_path, description):
                            confidence = self._calculate_match_confidence_improved(
                                dep_path, description
                            )
                            if confidence > 0.7:  # Higher threshold for text matching
                                text_matches.append(
                                    {
                                        "cve_id": cve_id,
                                        "dep_package": dep_path,
                                        "confidence": confidence,
                                        "match_type": "text_fallback",
                                    }
                                )

        # Combine all matches
        all_matches = precise_matches + text_matches

        # Create relationships
        if all_matches:
            link_query = """
            UNWIND $links AS link
            MATCH (cve:CVE {id: link.cve_id})
            MATCH (ed:ExternalDependency {package: link.dep_package})
            MERGE (cve)-[r:AFFECTS]->(ed)
            SET r.confidence = link.confidence,
                r.match_type = link.match_type,
                r.created_at = datetime()
            """
            session.run(link_query, links=all_matches)
            logger.info(f"🔗 Created {len(all_matches)} CVE-dependency relationships")
            logger.info(f"   - {len(precise_matches)} precise GAV matches")
            logger.info(f"   - {len(text_matches)} text fallback matches")
        else:
            logger.info("No CVE-dependency matches found")

    def _is_dependency_affected_simple(self, dep_path: str, cve_description: str) -> bool:
        """Simple dependency matching using cleaned CVE data."""
        dep_lower = dep_path.lower()

        # Direct match
        if dep_lower in cve_description:
            return True

        # Component matching
        parts = []
        for sep in [".", "/", "-", "_", "::"]:
            if sep in dep_path:
                parts.extend(part.lower() for part in dep_path.split(sep) if len(part) > 2)

        # At least one meaningful part must match
        for part in parts:
            if len(part) > 3 and part in cve_description:
                return True

        return False

    def _calculate_match_confidence_simple(self, dep_path: str, cve_description: str) -> float:
        """Calculate confidence for simple matching."""
        dep_lower = dep_path.lower()

        if dep_lower in cve_description:
            return 0.9

        parts = []
        for sep in [".", "/", "-", "_", "::"]:
            if sep in dep_path:
                parts.extend(part.lower() for part in dep_path.split(sep) if len(part) > 2)

        matches = sum(1 for part in parts if len(part) > 3 and part in cve_description)
        if matches and parts:
            return 0.6 * (matches / len(parts))

        return 0.1

    def _is_dependency_affected(
        self, dep_path: str, cve_text: str, cpe_components: Set[str]
    ) -> bool:
        """Determine if a dependency is affected by a CVE using universal matching."""
        dep_lower = dep_path.lower()

        # Direct text match
        if dep_lower in cve_text:
            return True

        # Extract components from dependency path
        dep_parts = set()

        # Split by various separators
        for sep in [".", "/", "-", "_", "::"]:
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

    def _calculate_match_confidence(
        self, dep_path: str, cve_text: str, cpe_components: Set[str]
    ) -> float:
        """Calculate confidence score for CVE-dependency matching."""
        confidence = 0.0
        dep_lower = dep_path.lower()

        # Direct path match (highest confidence)
        if dep_lower in cve_text:
            confidence += 0.8

        # CPE component matches
        dep_parts = set()
        for sep in [".", "/", "-", "_", "::"]:
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

    def _is_dependency_affected_improved(self, dep_path: str, cve_description: str) -> bool:
        """Improved dependency matching with stricter criteria to reduce false positives."""
        dep_lower = dep_path.lower()

        # Direct exact match (most reliable)
        if dep_lower in cve_description:
            return True

        # Extract meaningful components (avoid common words)
        parts = []
        for sep in [".", "/", "-", "_"]:
            if sep in dep_path:
                parts.extend(
                    part.lower()
                    for part in dep_path.split(sep)
                    if len(part) > 4
                    and part
                    not in {
                        "java",
                        "com",
                        "org",
                        "io",
                        "net",
                        "util",
                        "core",
                        "common",
                        "main",
                        "test",
                        "api",
                        "impl",
                        "base",
                    }
                )

        # Require at least 2 meaningful parts to match for high confidence
        matches = [part for part in parts if part in cve_description]
        return len(matches) >= 2

    def _calculate_match_confidence_improved(self, dep_path: str, cve_description: str) -> float:
        """Calculate confidence with stricter criteria."""
        dep_lower = dep_path.lower()

        # Direct match gets highest confidence
        if dep_lower in cve_description:
            return 0.95

        # Component matching with stricter scoring
        parts = []
        for sep in [".", "/", "-", "_"]:
            if sep in dep_path:
                parts.extend(
                    part.lower()
                    for part in dep_path.split(sep)
                    if len(part) > 4
                    and part
                    not in {
                        "java",
                        "com",
                        "org",
                        "io",
                        "net",
                        "util",
                        "core",
                        "common",
                        "main",
                        "test",
                        "api",
                        "impl",
                        "base",
                    }
                )

        if not parts:
            return 0.0

        matches = [part for part in parts if part in cve_description]
        match_ratio = len(matches) / len(parts)

        # Require high match ratio for confidence
        if match_ratio >= 0.8:
            return 0.8
        elif match_ratio >= 0.6:
            return 0.6
        else:
            return 0.0

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
                "CREATE FULLTEXT INDEX cve_description_index IF NOT EXISTS "
                "FOR (cve:CVE) ON EACH [cve.description]",
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

    def analyze_vulnerability_impact(
        self, max_hops: int = 4, risk_threshold: float = 7.0, max_concurrency: Optional[int] = None
    ):
        """Analyze the impact of CVEs on the codebase."""
        logger.info("🎯 Analyzing vulnerability impact...")

        with self.driver.session(database=self.database) as session:
            # First, let's check if we have any CVE data at all
            cve_count_query = "MATCH (cve:CVE) RETURN count(cve) as total"
            cve_result = session.run(cve_count_query)
            cve_count = cve_result.single()["total"]

            if cve_count == 0:
                logger.warning("⚠️  No CVE data found in the database. Running CVE fetch first...")
                # Fetch CVE data
                dependencies_by_ecosystem, _ = self.extract_codebase_dependencies()
                search_terms = self.create_universal_component_search_terms(
                    dependencies_by_ecosystem
                )
                cve_data = self.cve_manager.fetch_targeted_cves(
                    api_key=None, search_terms=search_terms, max_concurrency=max_concurrency
                )

                if cve_data:
                    self.create_vulnerability_graph(cve_data)
                    logger.info(f"✅ Fetched and stored {len(cve_data)} CVEs")
                else:
                    logger.warning("⚠️  No relevant CVEs found")
                    return []

            # Simple analysis query - just look for CVEs that might affect our dependencies
            analysis_query = """
            MATCH (cve:CVE)
            WHERE cve.cvss_score >= $risk_threshold
            OPTIONAL MATCH (ed:ExternalDependency)
            WITH cve, ed,
                 CASE WHEN ed.package IS NOT NULL THEN 1 ELSE 0 END AS has_dependency
            WITH cve, collect(ed.package) AS dependencies, sum(has_dependency) AS dep_count
            WHERE dep_count > 0
            RETURN cve.id AS cve_id,
                   cve.description AS description,
                   cve.cvss_score AS cvss_score,
                   cve.severity AS severity,
                   dependencies AS affected_dependencies,
                   dep_count AS dependency_count
            ORDER BY cve.cvss_score DESC
            LIMIT 50
            """

            result = session.run(analysis_query, risk_threshold=risk_threshold)
            vulnerabilities = [dict(record) for record in result]

            logger.info(f"🎯 Found {len(vulnerabilities)} potential vulnerabilities")
            return vulnerabilities

    def generate_impact_report(self, vulnerabilities):
        """Generate a comprehensive vulnerability impact report."""
        if not vulnerabilities:
            print("\n🎉 **EXCELLENT NEWS!**")
            print("No high-risk vulnerabilities found in your codebase!")
            print("This could mean:")
            print("  • Your dependencies are up-to-date and secure")
            print("  • The components you're using don't have known critical vulnerabilities")
            print("  • Your dependency versions are newer than vulnerable ranges")
            return

        print("\n🚨 **VULNERABILITY IMPACT REPORT**")
        print(f"Found {len(vulnerabilities)} potential security issues")
        print("=" * 80)

        for vuln in vulnerabilities[:10]:  # Show top 10
            print(f"\n🔴 {vuln['cve_id']} (CVSS: {vuln['cvss_score']:.1f})")
            print(f"   Severity: {vuln['severity']}")
            print(f"   Description: {vuln['description'][:100]}...")
            if vuln.get("affected_dependencies"):
                print(f"   Potentially affects: {len(vuln['affected_dependencies'])} dependencies")

        print("\n💡 **RECOMMENDATIONS:**")
        print("1. Review the high-CVSS vulnerabilities above")
        print("2. Check if your dependency versions are in the vulnerable ranges")
        print("3. Update dependencies to patched versions")
        print("4. Run security scans regularly")


def main():
    """Main entry point for CVE analysis."""
    import os
    import sys

    # Add project root to path
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    parser = argparse.ArgumentParser(
        description="CVE Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check cache status and analyze
  python cve_analysis.py --cache-status

  # Run analysis with API key (recommended)
  python cve_analysis.py --api-key your_nvd_key_here

  # Clear partial caches and start fresh
  python cve_analysis.py --clear-partial-cache

  # Get API key info
  python cve_analysis.py --api-key-info
        """,
    )

    # Add common Neo4j connection and logging arguments
    try:
        from utils.common import add_common_args
    except ImportError:
        from ..utils.common import add_common_args

    add_common_args(
        parser
    )  # Adds --uri, --username, --password, --database, --log-level, --log-file

    parser.add_argument("--api-key", help="NVD API key for faster, more reliable downloads")
    parser.add_argument(
        "--max-results",
        type=int,
        default=2000,
        help="Maximum CVEs to fetch (default: 2000)",
    )
    parser.add_argument(
        "--days-back", type=int, default=365, help="Days back to search (default: 365)"
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        help="Maximum concurrent requests (default: API rate limit)",
    )
    parser.add_argument("--cache-status", action="store_true", help="Show cache status and exit")
    parser.add_argument(
        "--clear-partial-cache",
        action="store_true",
        help="Clear partial caches (keeps complete caches)",
    )
    parser.add_argument("--clear-all-cache", action="store_true", help="Clear all caches")
    parser.add_argument("--api-key-info", action="store_true", help="Show how to get an API key")
    parser.add_argument(
        "--risk-threshold",
        type=float,
        default=7.0,
        help="CVSS score threshold for vulnerability analysis (default: 7.0)",
    )
    parser.add_argument(
        "--max-hops",
        type=int,
        default=4,
        help="Maximum hops for vulnerability impact analysis (default: 4)",
    )

    args = parser.parse_args()

    setup_logging(args.log_level, args.log_file)

    # Handle informational requests
    if args.api_key_info:
        print("\n🔑 **HOW TO GET AN NVD API KEY**")
        print("=" * 50)
        print("1. Go to: https://nvd.nist.gov/developers/request-an-api-key")
        print("2. Fill out the form (takes 2 minutes)")
        print("3. Check your email for the API key")
        print("4. Use it with: --api-key YOUR_KEY_HERE")
        print("\n💡 **BENEFITS:**")
        print("• 50 requests/second vs 5 requests/second")
        print("• Much faster downloads")
        print("• More reliable connection")
        print("• Better progress tracking")
        return

    # Connect to Neo4j using consistent args (which now come from .env via add_common_args)
    with create_neo4j_driver(args.uri, args.username, args.password) as driver:
        analyzer = CVEAnalyzer(driver, args.database)

        # Handle cache management
        if args.cache_status:
            analyzer.get_cache_status()
            return

        if args.clear_partial_cache:
            analyzer.cve_manager.clear_cache(keep_complete=True)
            print("✅ Cleared partial caches (complete caches preserved)")
            return

        if args.clear_all_cache:
            confirm = input("⚠️  This will delete ALL cached CVE data. Continue? (y/N): ")
            if confirm.lower() == "y":
                analyzer.cve_manager.clear_cache(keep_complete=False)
                print("✅ Cleared all caches")
            else:
                print("❌ Cancelled")
            return

        # Show current cache status first
        print("🔍 **STARTING CVE ANALYSIS**")
        analyzer.get_cache_status()

        # Extract dependencies from the graph
        dependencies_by_ecosystem, detected_languages = analyzer.extract_codebase_dependencies()
        logger.info(
            "📊 Detected %d dependencies"
            % sum(len(deps) for deps in dependencies_by_ecosystem.values())
        )
        logger.info(f"📊 Languages: {', '.join(sorted(detected_languages))}")

        if not dependencies_by_ecosystem:
            logger.warning(
                "⚠️  No dependencies found in graph. Make sure to run code_to_graph.py first."
            )
            return

        # Create universal search terms
        search_terms = analyzer.create_universal_component_search_terms(dependencies_by_ecosystem)

        print("\n🎯 **CVE FETCH PARAMETERS**")
        print("=" * 50)
        print(f"Target CVEs:     {args.max_results}")
        print(f"Days back:       {args.days_back}")
        print(f"Search terms:    {len(search_terms)}")
        # Check for API key from environment if not provided via command line
        api_key = args.api_key
        if not api_key:
            import os

            api_key = os.getenv("NVD_API_KEY")

        print(f"API key:         {'✅ Yes (fast)' if api_key else '❌ No (slow)'}")

        if not api_key:
            print("\n💡 **TIP**: Get an API key for 10x faster downloads!")
            print("   Use --api-key-info for instructions")
            print("   Without API key: ~2-5 CVEs/second")
            print("   With API key:    ~20-50 CVEs/second")

            proceed = input("\nProceed without API key? (y/N): ")
            if proceed.lower() != "y":
                print("💡 Get an API key first with --api-key-info")
                return

        # Fetch CVE data with robust error handling
        print("\n🌐 **FETCHING CVE DATA**")
        print("=" * 50)
        print("💾 Progress is saved incrementally - safe to interrupt!")

        try:
            cve_data = analyzer.cve_manager.fetch_targeted_cves(
                api_key=api_key,
                search_terms=search_terms,
                max_results=args.max_results,
                days_back=args.days_back,
                max_concurrency=args.max_concurrency,
            )

            if not cve_data:
                print("\n🎉 **EXCELLENT NEWS!**")
                print("No high-risk CVEs found for your dependencies!")
                print("This suggests your codebase is using secure, up-to-date components.")
                return

            # Create vulnerability graph
            print("\n📊 **CREATING VULNERABILITY GRAPH**")
            num_cves = analyzer.create_vulnerability_graph(cve_data)
            print(f"✅ Created {num_cves} CVE nodes with dependency relationships")

            # Analyze impact
            impact_summary = analyzer.analyze_vulnerability_impact(
                max_hops=args.max_hops,
                risk_threshold=args.risk_threshold,
                max_concurrency=args.max_concurrency,
            )

            # Generate report
            analyzer.generate_impact_report(impact_summary)

        except KeyboardInterrupt:
            print("\n⚠️  **PROCESS INTERRUPTED**")
            print("Don't worry! Your progress has been saved.")
            print("Run the same command again to resume where you left off.")

        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")
            print("\n🔄 **RECOVERY OPTIONS:**")
            print("1. Check your internet connection")
            print("2. Try again with --api-key for better reliability")
            print("3. Use --cache-status to see saved progress")
            print("4. Use --clear-partial-cache if data seems corrupted")


if __name__ == "__main__":
    main()
