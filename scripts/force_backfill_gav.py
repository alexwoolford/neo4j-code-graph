#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def _clone_repo(repo_url: str) -> Path:
    work = Path(tempfile.mkdtemp(prefix="gav_repo_"))
    subprocess.run(["git", "clone", "--depth", "1", repo_url, str(work)], check=True)
    return work


def main() -> int:
    parser = argparse.ArgumentParser(description="Force backfill GAV onto ExternalDependency nodes")
    parser.add_argument("--repo", required=True, help="Git URL or local path of the source repository")
    parser.add_argument("--uri", help="Neo4j URI (overrides env/.env)")
    parser.add_argument("--user", help="Neo4j username (overrides env/.env)")
    parser.add_argument("--password", help="Neo4j password (overrides env/.env)")
    parser.add_argument("--database", help="Neo4j database name (overrides env/.env)")
    args = parser.parse_args()

    # Imports path-safe
    import sys

    sys.path.insert(0, os.getcwd())
    try:
        from src.analysis.dependency_extraction import (
            extract_enhanced_dependencies_for_neo4j,
        )
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        from analysis.dependency_extraction import (  # type: ignore
            extract_enhanced_dependencies_for_neo4j,
        )
        from utils.common import create_neo4j_driver, get_neo4j_config  # type: ignore

    repo_root = Path(args.repo)
    if not repo_root.exists():
        repo_root = _clone_repo(args.repo)

    mapping = extract_enhanced_dependencies_for_neo4j(repo_root)
    gav_triples = []
    for k, v in mapping.items():
        parts = str(k).split(":")
        if len(parts) == 3:
            g, a, ver = parts
            gav_triples.append({"g": g, "a": a, "v": v})

    uri, user, pwd, db = get_neo4j_config()
    if args.uri:
        uri = args.uri
    if args.user:
        user = args.user
    if args.password:
        pwd = args.password
    if args.database:
        db = args.database

    updated = 0
    with create_neo4j_driver(uri, user, pwd) as driver:
        with driver.session(database=db) as s:
            # Create property tokens if missing
            s.run(
                """
                MATCH (e:ExternalDependency)
                SET e.version = NULL, e.group_id = NULL, e.artifact_id = NULL
                """
            ).consume()

            # Merge GA nodes from GAV triples
            if gav_triples:
                s.run(
                    """
                    UNWIND $gav AS dep
                    MERGE (e:ExternalDependency {group_id: dep.g, artifact_id: dep.a})
                    SET e.version = dep.v
                    RETURN 0
                    """,
                    gav=gav_triples,
                ).consume()

            # Backfill onto package-keyed nodes
            s.run(
                """
                UNWIND $gav AS dep
                MATCH (e:ExternalDependency)
                WHERE e.package IS NOT NULL AND (e.package = dep.g OR e.package STARTS WITH dep.g)
                SET e.group_id = coalesce(e.group_id, dep.g),
                    e.artifact_id = coalesce(e.artifact_id, dep.a),
                    e.version = coalesce(e.version, dep.v)
                RETURN 0
                """,
                gav=gav_triples,
            ).consume()

            # Summaries
            total = s.run("MATCH (e:ExternalDependency) RETURN count(e) AS c").single()
            with_version = s.run(
                "MATCH (e:ExternalDependency) WHERE e.version IS NOT NULL RETURN count(e) AS c"
            ).single()
            sample = s.run(
                """
                MATCH (e:ExternalDependency)
                WHERE e.version IS NOT NULL
                RETURN e.package AS package, e.group_id AS group_id, e.artifact_id AS artifact_id, e.version AS version
                ORDER BY package, group_id, artifact_id LIMIT 10
                """
            ).data()

    print(
        json.dumps(
            {
                "gav_pairs": len(gav_triples),
                "total_external": int(total["c"]) if total else 0,
                "with_version": int(with_version["c"]) if with_version else 0,
                "sample": sample,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


