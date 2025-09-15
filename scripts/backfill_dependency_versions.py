#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _clone_repo(repo_url: str) -> Path:
    work = Path(tempfile.mkdtemp(prefix="deps_repo_"))
    subprocess.run(["git", "clone", "--depth", "1", repo_url, str(work)], check=True)
    return work


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill ExternalDependency.version in Neo4j from a repo"
    )
    parser.add_argument(
        "--repo", required=True, help="Git URL or local path of the source repository"
    )
    args = parser.parse_args()

    # Ensure local repo is importable
    sys.path.insert(0, os.getcwd())
    try:
        from src.analysis.dependency_extraction import (
            extract_enhanced_dependencies_for_neo4j,
        )
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        # Fallback to installed package paths
        from analysis.dependency_extraction import (  # type: ignore
            extract_enhanced_dependencies_for_neo4j,
        )
        from utils.common import create_neo4j_driver, get_neo4j_config  # type: ignore

    repo_root = Path(args.repo)
    if not repo_root.exists():
        # Assume URL and clone shallow
        repo_root = _clone_repo(args.repo)

    # Best-effort: try to materialize lockfile (ignore failures)
    if (repo_root / "gradlew").exists():
        try:
            subprocess.run(
                [
                    "bash",
                    "-lc",
                    f"cd {repo_root} && ./gradlew --no-daemon :dependencies --write-locks",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    mapping = extract_enhanced_dependencies_for_neo4j(repo_root)
    print(json.dumps({"extracted_keys": len(mapping)}, indent=2))

    uri, user, pwd, db = get_neo4j_config()
    updated = 0
    with create_neo4j_driver(uri, user, pwd) as driver:
        with driver.session(database=db) as s:
            # Ensure property keys exist to avoid UnknownPropertyKey warnings
            s.run(
                """
                MATCH (e:ExternalDependency)
                SET e.version = e.version,
                    e.group_id = e.group_id,
                    e.artifact_id = e.artifact_id
                """
            ).consume()
            pairs = list(mapping.items())
            batch = 1000
            for i in range(0, len(pairs), batch):
                part = pairs[i : i + batch]
                s.run(
                    """
                    UNWIND $pairs AS p
                    WITH p[0] AS key, p[1] AS ver
                    WITH key, ver, CASE WHEN key CONTAINS ':' THEN split(key, ':') ELSE null END AS gav
                    // Full G:A:V → set on matching G/A nodes
                    CALL {
                      WITH key, ver, gav
                      WITH ver, gav WHERE gav IS NOT NULL AND size(gav)=3
                      MATCH (e:ExternalDependency {group_id: gav[0], artifact_id: gav[1]})
                      SET e.group_id = coalesce(e.group_id, gav[0]),
                          e.artifact_id = coalesce(e.artifact_id, gav[1]),
                          e.version = ver
                      RETURN 0 AS r1
                    }
                    // Full G:A:V → if no GA node exists, create it
                    CALL {
                      WITH key, ver, gav
                      WITH key, ver, gav WHERE gav IS NOT NULL AND size(gav)=3
                      MERGE (e:ExternalDependency {group_id: gav[0], artifact_id: gav[1]})
                      ON CREATE SET e.version = ver, e.package = coalesce(e.package, gav[0])
                      RETURN 0 AS r1c
                    }
                    // Full G:A:V → package prefix fallback by group
                    CALL {
                      WITH key, ver, gav
                      WITH ver, gav WHERE gav IS NOT NULL AND size(gav)=3
                      MATCH (e:ExternalDependency)
                      WHERE e.package IS NOT NULL AND e.package STARTS WITH gav[0]
                      SET e.group_id = coalesce(e.group_id, gav[0]),
                          e.version = coalesce(e.version, ver)
                      RETURN 0 AS r1b
                    }
                    // Two-part G:A → set version
                    CALL {
                      WITH key, ver, gav
                      WITH key, ver WHERE gav IS NULL OR size(gav)<>3
                      WITH split(key, ':') AS ga, ver WHERE size(ga)=2
                      MATCH (e:ExternalDependency {group_id: ga[0], artifact_id: ga[1]})
                      SET e.group_id = coalesce(e.group_id, ga[0]),
                          e.artifact_id = coalesce(e.artifact_id, ga[1]),
                          e.version = ver
                      RETURN 0 AS r2
                    }
                    // Two-part G:A → if missing, create GA node with version
                    CALL {
                      WITH key, ver, gav
                      WITH key, ver WHERE gav IS NULL OR size(gav)<>3
                      WITH split(key, ':') AS ga, ver WHERE size(ga)=2
                      MERGE (e:ExternalDependency {group_id: ga[0], artifact_id: ga[1]})
                      ON CREATE SET e.version = ver, e.package = coalesce(e.package, ga[0])
                      RETURN 0 AS r2c
                    }
                    // Two-part G:A → package prefix fallback by group
                    CALL {
                      WITH key, ver, gav
                      WITH key, ver WHERE gav IS NULL OR size(gav)<>3
                      WITH split(key, ':') AS ga, ver WHERE size(ga)=2
                      MATCH (e:ExternalDependency)
                      WHERE e.package IS NOT NULL AND e.package STARTS WITH ga[0]
                      SET e.group_id = coalesce(e.group_id, ga[0]),
                          e.version = coalesce(e.version, ver)
                      RETURN 0 AS r2b
                    }
                    // Package fallback update (coarse)
                    CALL {
                      WITH key, ver
                      MATCH (e:ExternalDependency)
                      WHERE e.package IS NOT NULL AND (e.package = key OR key STARTS WITH e.package OR e.package STARTS WITH key)
                      SET e.version = coalesce(e.version, ver)
                      RETURN 0 AS r3
                    }
                    // If key looks like GA or GAV, try to backfill group/artifact on package-coarse matches
                    CALL {
                      WITH key
                      WITH key WHERE key CONTAINS ':'
                      WITH split(key, ':') AS parts
                      WITH parts WHERE size(parts) >= 2
                      MATCH (e:ExternalDependency)
                      WHERE e.package IS NOT NULL AND (e.package = parts[0] OR e.package STARTS WITH parts[0])
                      SET e.group_id = coalesce(e.group_id, parts[0]),
                          e.artifact_id = coalesce(e.artifact_id, CASE WHEN size(parts) >= 2 THEN parts[1] ELSE e.artifact_id END)
                      RETURN 0 AS r4
                    }
                    RETURN 0 AS done
                    """,
                    pairs=part,
                ).consume()
                updated += len(part)

    # Print summary
    with create_neo4j_driver(uri, user, pwd) as driver:
        with driver.session(database=db) as s:
            rec = s.run(
                """
                MATCH (e:ExternalDependency)
                RETURN count(e) AS total,
                       sum(CASE WHEN e.version IS NOT NULL THEN 1 ELSE 0 END) AS with_version
                """
            ).single()
            sample = s.run(
                """
                MATCH (e:ExternalDependency)
                WHERE e.version IS NOT NULL
                RETURN e.package AS package, e.group_id AS group_id, e.artifact_id AS artifact_id, e.version AS version
                ORDER BY package LIMIT 10
                """
            ).data()
            print(
                json.dumps(
                    {
                        "updated_pairs": updated,
                        "total_external": int(rec["total"] if rec else 0),
                        "with_version": int(rec["with_version"] if rec else 0),
                        "sample": sample,
                    },
                    indent=2,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
