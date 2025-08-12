#!/usr/bin/env python3
"""
Temporal codebase analyses: change coupling and hotspots.

Provides focused, testable functions for file co-change coupling and hotspot scoring.
"""

import argparse
import logging

try:
    from utils.common import add_common_args, create_neo4j_driver, setup_logging
except ImportError:
    from ..utils.common import add_common_args, create_neo4j_driver, setup_logging


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Temporal analyses: change coupling and hotspots")
    add_common_args(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Coupling
    coupling = subparsers.add_parser("coupling", help="Analyze file change coupling")
    coupling.add_argument("--min-support", type=int, default=5, help="Minimum co-change support")
    coupling.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.0,
        help="Minimum confidence to keep (0-1)",
    )
    coupling.add_argument(
        "--create-relationships",
        action="store_true",
        help="Write CO_CHANGED relationships",
    )

    # Hotspots
    hotspots = subparsers.add_parser("hotspots", help="Analyze code hotspots")
    hotspots.add_argument("--days", type=int, default=365, help="Window in days")
    hotspots.add_argument(
        "--min-changes", type=int, default=3, help="Minimum recent changes to include"
    )
    hotspots.add_argument("--top-n", type=int, default=15, help="Top-N rows to return")
    hotspots.add_argument("--write-back", action="store_true", help="Write scores to File nodes")

    return parser.parse_args()


def run_coupling(
    driver,
    database: str,
    min_support: int = 5,
    confidence_threshold: float = 0.0,
    write: bool = False,
) -> None:
    logger.info(
        "Analyzing file change coupling (min_support=%d, confidence>=%.2f, write=%s)",
        min_support,
        confidence_threshold,
        write,
    )

    # Use canonical ordering to avoid duplicate pairs
    read_query = """
    MATCH (c:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f1:File)
    MATCH (c)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f2:File)
    WHERE f1.path < f2.path
    WITH f1, f2, count(DISTINCT c) AS support
    WHERE support >= $min_support
    // Compute confidence based on individual change frequencies
    MATCH (c1:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f1)
    WITH f1, f2, support, toFloat(count(DISTINCT c1)) AS f1_changes
    MATCH (c2:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f2)
    WITH f1, f2, support, f1_changes, toFloat(count(DISTINCT c2)) AS f2_changes
    WITH f1, f2, support,
         CASE WHEN f1_changes > 0 THEN support / f1_changes ELSE 0 END AS conf1,
         CASE WHEN f2_changes > 0 THEN support / f2_changes ELSE 0 END AS conf2
    WITH f1, f2, support, (conf1 + conf2) / 2.0 AS confidence
    WHERE confidence >= $confidence_threshold
    RETURN f1.path AS file1, f2.path AS file2, support, confidence
    ORDER BY support DESC, confidence DESC, file1, file2
    """

    write_query = """
    MATCH (c:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f1:File)
    MATCH (c)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f2:File)
    WHERE f1.path < f2.path
    WITH f1, f2, count(DISTINCT c) AS support
    WHERE support >= $min_support
    MATCH (c1:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f1)
    WITH f1, f2, support, toFloat(count(DISTINCT c1)) AS f1_changes
    MATCH (c2:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f2)
    WITH f1, f2, support, f1_changes, toFloat(count(DISTINCT c2)) AS f2_changes
    WITH f1, f2, support,
         CASE WHEN f1_changes > 0 THEN support / f1_changes ELSE 0 END AS conf1,
         CASE WHEN f2_changes > 0 THEN support / f2_changes ELSE 0 END AS conf2
    WITH f1, f2, support, (conf1 + conf2) / 2.0 AS confidence
    WHERE confidence >= $confidence_threshold
    MERGE (f1)-[cc:CO_CHANGED]->(f2)
    SET cc.support = support,
        cc.confidence = confidence,
        cc.lastUpdated = datetime()
    RETURN f1.path AS file1, f2.path AS file2, support, confidence
    ORDER BY support DESC, confidence DESC, file1, file2
    """

    with driver.session(database=database) as session:
        result = session.run(
            write_query if write else read_query,
            {
                "min_support": int(min_support),
                "confidence_threshold": float(confidence_threshold),
            },
        )
        rows = list(result)

    logger.info("Computed %d co-change pairs", len(rows))
    # Print concise summary to stdout
    print("\nTop change-coupled files:")
    for row in rows[:20]:
        print(
            f"  {row['support']:>4d} | {row['confidence']:.2f} | {row['file1']}  <>  {row['file2']}"
        )


def run_hotspots(
    driver,
    database: str,
    days: int = 365,
    min_changes: int = 3,
    top_n: int = 15,
    write_back: bool = False,
) -> None:
    logger.info(
        "Analyzing hotspots (days=%d, min_changes=%d, top_n=%d, write=%s)",
        days,
        min_changes,
        top_n,
        write_back,
    )

    # Score formula emphasizes recency and complexity proxies
    read_query = """
    MATCH (f:File)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(c:Commit)
    WHERE c.date > datetime() - duration({days: $days})
    WITH f, count(DISTINCT c) AS recent_changes,
         coalesce(f.method_count, 0) AS method_count,
         coalesce(f.total_lines, 0) AS total_lines
    WHERE recent_changes >= $min_changes
    WITH f, recent_changes, method_count, total_lines,
         (recent_changes * 1.0) + (method_count / 20.0) + (total_lines / 1000.0) AS score
    RETURN f.path AS path, recent_changes, method_count, total_lines, score
    ORDER BY score DESC
    LIMIT $top_n
    """

    write_query = """
    MATCH (f:File)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(c:Commit)
    WHERE c.date > datetime() - duration({days: $days})
    WITH f, count(DISTINCT c) AS recent_changes,
         coalesce(f.method_count, 0) AS method_count,
         coalesce(f.total_lines, 0) AS total_lines
    WHERE recent_changes >= $min_changes
    WITH f, recent_changes, method_count, total_lines,
         (recent_changes * 1.0) + (method_count / 20.0) + (total_lines / 1000.0) AS score
    SET f.recent_changes = recent_changes,
        f.hotspot_score = score,
        f.lastHotspotUpdate = datetime()
    RETURN f.path AS path, recent_changes, method_count, total_lines, score
    ORDER BY score DESC
    LIMIT $top_n
    """

    with driver.session(database=database) as session:
        result = session.run(
            write_query if write_back else read_query,
            {
                "days": int(days),
                "min_changes": int(min_changes),
                "top_n": int(top_n),
            },
        )
        rows = list(result)

    logger.info("Computed hotspot scores for top %d files", len(rows))
    print("\nTop hotspots:")
    for row in rows:
        print(
            f"  {row['score']:.2f} | {row['recent_changes']:3d} rc | {row['method_count']:4d} m | {row['total_lines']:6d} loc | {row['path']}"
        )


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level, args.log_file)
    with create_neo4j_driver(args.uri, args.username, args.password) as driver:
        if args.command == "coupling":
            run_coupling(
                driver,
                database=args.database,
                min_support=args.min_support,
                confidence_threshold=args.confidence_threshold,
                write=args.create_relationships,
            )
        elif args.command == "hotspots":
            run_hotspots(
                driver,
                database=args.database,
                days=args.days,
                min_changes=args.min_changes,
                top_n=args.top_n,
                write_back=args.write_back,
            )


if __name__ == "__main__":
    main()
