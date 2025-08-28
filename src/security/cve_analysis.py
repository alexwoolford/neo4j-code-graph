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

from __future__ import annotations

import argparse
import logging
from typing import Any

try:
    from src.security.types import CleanCVE  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from security.types import CleanCVE  # type: ignore

try:
    from src.security.core import CVEAnalyzerCore  # type: ignore[attr-defined]
    from src.security.graph_writer import (  # type: ignore[attr-defined]
        create_vulnerability_graph,
        link_cves_to_dependencies,
    )
    from src.security.report import generate_impact_report  # type: ignore[attr-defined]
    from src.utils.common import create_neo4j_driver, setup_logging  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from security.core import CVEAnalyzerCore  # type: ignore
    from security.graph_writer import (  # type: ignore
        create_vulnerability_graph,
        link_cves_to_dependencies,
    )
    from security.report import generate_impact_report  # type: ignore
    from utils.common import create_neo4j_driver, setup_logging  # type: ignore

# Avoid sys.path hacks; modules should be importable via package installation or repo context


logger = logging.getLogger(__name__)


class CVEAnalyzer(CVEAnalyzerCore):
    """Facade over core + graph writes and reporting."""

    @staticmethod
    def load_cve_data(file_path: str):
        import json

        with open(file_path) as f:
            return json.load(f)

    def create_vulnerability_graph(self, cve_data: list[CleanCVE]) -> int:
        with self._session() as session:
            return create_vulnerability_graph(session, cve_data)

    def _link_cves_to_dependencies(self, *args: Any) -> int:
        """Link CVEs to dependencies.

        Backward-compatible signature:
        - Preferred: _link_cves_to_dependencies(cve_data)
        - Legacy (tests/docs): _link_cves_to_dependencies(session, cve_data)
        """
        if len(args) == 1:
            cve_data = args[0]
            with self._session() as session:
                return link_cves_to_dependencies(session, cve_data)
        elif len(args) == 2:
            session, cve_data = args
            return link_cves_to_dependencies(session, cve_data)
        else:
            raise TypeError("_link_cves_to_dependencies expects (cve_data) or (session, cve_data)")

    # Note: legacy helper retained for backwards-compatibility in tests and docs
    @staticmethod
    def _get_severity(cvss_score: float) -> str:
        """Get severity level from CVSS score."""
        if cvss_score >= 9.0:
            return "CRITICAL"
        if cvss_score >= 7.0:
            return "HIGH"
        if cvss_score >= 4.0:
            return "MEDIUM"
        if cvss_score > 0.0:
            return "LOW"
        return "NONE"

    def get_cache_status(self):
        return super().get_cache_status()

    # Removed unused legacy simple-matching helpers to reduce maintenance surface

    # Removed unused legacy simple-matching helpers to reduce maintenance surface

    # Removed unused legacy universal-matching helper to reduce maintenance surface

    # Removed unused legacy universal-matching helper to reduce maintenance surface

    @staticmethod
    def _is_dependency_affected_improved(dep_path: str, cve_description: str) -> bool:
        """Improved dependency matching with stricter criteria to reduce false positives."""
        dep_lower = dep_path.lower()

        if dep_lower in cve_description:
            return True

        parts = _extract_meaningful_parts(dep_path)
        matches: list[str] = [part for part in parts if part in cve_description]
        return len(matches) >= 2

    @staticmethod
    def _calculate_match_confidence_improved(dep_path: str, cve_description: str) -> float:
        """Calculate confidence with stricter criteria."""
        dep_lower = dep_path.lower()

        # Direct match gets highest confidence
        if dep_lower in cve_description:
            return 0.95

        # Component matching with stricter scoring
        parts = _extract_meaningful_parts(dep_path)

        if not parts:
            return 0.0

        matches: list[str] = [part for part in parts if part in cve_description]
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

        with self._session() as session:
            try:
                session.run(
                    "CREATE INDEX cve_cvss_score IF NOT EXISTS FOR (cve:CVE) ON (cve.cvss_score)"
                )
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.debug("Index already exists: cve_cvss_score")
                else:
                    logger.warning(f"Failed to create index cve_cvss_score: {e}")

            try:
                session.run(
                    "CREATE INDEX cve_severity IF NOT EXISTS FOR (cve:CVE) ON (cve.severity)"
                )
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.debug("Index already exists: cve_severity")
                else:
                    logger.warning(f"Failed to create index cve_severity: {e}")

            try:
                session.run(
                    "CREATE INDEX cve_published IF NOT EXISTS FOR (cve:CVE) ON (cve.published)"
                )
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.debug("Index already exists: cve_published")
                else:
                    logger.warning(f"Failed to create index cve_published: {e}")

            try:
                session.run(
                    "CREATE FULLTEXT INDEX cve_description_index IF NOT EXISTS FOR (cve:CVE) ON EACH [cve.description]"
                )
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.debug("Index already exists: cve_description_index")
                else:
                    logger.warning(f"Failed to create fulltext index: {e}")

    def analyze_vulnerability_impact(
        self, max_hops: int = 4, risk_threshold: float = 7.0, max_concurrency: int | None = None
    ) -> list[dict[str, Any]]:
        """Analyze the impact of CVEs on the codebase."""
        logger.info("🎯 Analyzing vulnerability impact...")

        with self._session() as session:
            # First, let's check if we have any CVE data at all
            cve_count_query = "MATCH (cve:CVE) RETURN count(cve) as total"
            cve_result = session.run(cve_count_query)
            cve_single = cve_result.single()
            cve_count = int(cve_single["total"]) if cve_single and "total" in cve_single else 0

            if cve_count == 0:
                logger.info("ℹ️  No CVE nodes present; skipping impact analysis.")
                return []

            # Simple analysis query - just look for CVEs that might affect our dependencies
            result = session.run(
                """
                MATCH (cve:CVE)
                WHERE cve.cvss_score >= $risk_threshold
                OPTIONAL MATCH (cve)-[:AFFECTS]->(ed:ExternalDependency)
                WITH cve, collect(ed.package) AS dependencies
                WITH cve, [d IN dependencies WHERE d IS NOT NULL] AS deps
                WITH cve, deps, size(deps) AS dep_count
                WHERE dep_count > 0
                RETURN cve.id AS cve_id,
                       cve.description AS description,
                       cve.cvss_score AS cvss_score,
                       cve.severity AS severity,
                       deps AS affected_dependencies,
                       dep_count AS dependency_count
                ORDER BY cve.cvss_score DESC
                LIMIT 50
                """,
                parameters={"risk_threshold": float(risk_threshold)},
            )
            vulnerabilities = [dict(record) for record in result]

            logger.info(f"🎯 Found {len(vulnerabilities)} potential vulnerabilities")
            return vulnerabilities

    @staticmethod
    def generate_impact_report(vulnerabilities: list[dict[str, Any]]):
        generate_impact_report(vulnerabilities)

        print("\n💡 **RECOMMENDATIONS:**")
        print("1. Review the high-CVSS vulnerabilities above")
        print("2. Check if your dependency versions are in the vulnerable ranges")
        print("3. Update dependencies to patched versions")
        print("4. Run security scans regularly")


def _extract_meaningful_parts(dep_path: str) -> list[str]:
    parts: list[str] = []
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
    return parts


def main():
    """Main entry point for CVE analysis."""

    # Avoid sys.path hacks; prefer installed package or repo execution

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
        from src.utils.common import add_common_args  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        from utils.common import add_common_args  # type: ignore

    add_common_args(
        parser
    )  # Adds --uri, --username, --password, --database, --log-level, --log-file

    parser.add_argument("--api-key", help="NVD API key for faster, more reliable downloads")
    parser.add_argument(
        "--proceed-without-key",
        action="store_true",
        help="Proceed to fetch CVEs even if no NVD API key is provided",
    )
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
    try:
        from src.utils.common import resolve_neo4j_args  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        from utils.common import resolve_neo4j_args  # type: ignore

    _uri, _user, _pwd, _db = resolve_neo4j_args(
        args.uri, args.username, args.password, args.database
    )
    with create_neo4j_driver(_uri, _user, _pwd) as driver:
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

        if not api_key and not args.proceed_without_key:
            print("\n💡 **TIP**: Get an API key for 10x faster downloads!")
            print("   Use --api-key-info for instructions")
            print("   Without API key: ~2-5 CVEs/second")
            print("   With API key:    ~20-50 CVEs/second")
            print(
                "\nSkipping CVE fetch because no API key was provided and --proceed-without-key was not set."
            )
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
            # Report CVE nodes separately from relationships; linking is strict and may be zero
            print(f"✅ Created {num_cves} CVE nodes")

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
