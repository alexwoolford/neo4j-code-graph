#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(
            json.dumps({"error": "usage: update_dependency_versions.py /path/to/dependencies.json"})
        )
        return 1

    mapping_path = Path(sys.argv[1])
    if not mapping_path.exists():
        print(json.dumps({"error": f"not found: {mapping_path}"}))
        return 1

    versions = json.loads(mapping_path.read_text(encoding="utf-8"))
    # Normalize to str->str
    dep_versions: dict[str, str] = {str(k): str(v) for k, v in versions.items()}

    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        from utils.common import create_neo4j_driver, get_neo4j_config  # type: ignore

    uri, user, pwd, db = get_neo4j_config()
    report = {"updated": 0, "attempts": 0}

    def update_batch(pairs: list[tuple[str, str]]) -> int:
        from neo4j import Query

        q = Query(
            """
            UNWIND $pairs AS p
            WITH p[0] AS key, p[1] AS ver
            // Try match by full GAV
            WITH key, ver,
                 CASE WHEN key CONTAINS ':' THEN split(key, ':') ELSE null END AS gav
            CALL {
              WITH key, ver, gav
              WITH key, ver, gav WHERE gav IS NOT NULL AND size(gav) = 3
              MATCH (e:ExternalDependency)
              WHERE e.group_id = gav[0] AND e.artifact_id = gav[1]
              SET e.version = ver
              RETURN count(e) AS c
            }
            CALL {
              WITH key, ver, gav
              WITH key, ver WHERE gav IS NULL OR size(gav) <> 3
              // Two-part key: group:artifact
              WITH key, ver WHERE key CONTAINS ':'
              WITH split(key, ':') AS ga, ver
              MATCH (e:ExternalDependency)
              WHERE e.group_id = ga[0] AND e.artifact_id = ga[1]
              SET e.version = ver
              RETURN count(e) AS c
            }
            CALL {
              WITH key, ver
              // Package prefix fallback
              MATCH (e:ExternalDependency)
              WHERE e.package STARTS WITH key OR key STARTS WITH e.package
              SET e.version = coalesce(e.version, ver)
              RETURN count(e) AS c
            }
            RETURN 0 AS ok
            """
        )
        with create_neo4j_driver(uri, user, pwd) as driver:
            with driver.session(database=db) as s:
                s.run(q, pairs=pairs).consume()
        return len(pairs)

    items = list(dep_versions.items())
    batch = 500
    for i in range(0, len(items), batch):
        part = items[i : i + batch]
        report["attempts"] += len(part)
        update_batch(part)
        report["updated"] += len(part)

    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
