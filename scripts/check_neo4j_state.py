#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        from src.constants import EMBEDDING_PROPERTY
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception as e:  # pragma: no cover
        print(json.dumps({"error": f"import_error: {e}"}))
        return 0

    report: dict[str, object] = {
        "uri": None,
        "database": None,
        "calls_count": None,
        "pagerank_methods": None,
        "similarity_community_methods": None,
        "embeddings_methods": None,
        "external_dependencies": None,
        "external_with_version": None,
        "gds_version": None,
        "errors": [],
    }

    try:
        uri, user, pwd, db = get_neo4j_config()
        report["uri"] = uri
        report["database"] = db
    except Exception as e:
        errors = report.get("errors")
        if isinstance(errors, list):
            errors.append(f"config_error: {e}")
        print(json.dumps(report, indent=2))
        return 0

    try:
        with create_neo4j_driver(uri, user, pwd) as driver:
            with driver.session(database=db) as s:
                try:
                    calls = s.run("MATCH ()-[r:CALLS]->() RETURN count(r) AS c").single()
                    report["calls_count"] = int(calls["c"]) if calls else 0
                except Exception as e:
                    errors = report.get("errors")
                    if isinstance(errors, list):
                        errors.append(f"calls_query_error: {e}")

                try:
                    pr = s.run(
                        "MATCH (m:Method) WHERE m.pagerank_score IS NOT NULL RETURN count(m) AS c"
                    ).single()
                    report["pagerank_methods"] = int(pr["c"]) if pr else 0
                except Exception as e:
                    errors = report.get("errors")
                    if isinstance(errors, list):
                        errors.append(f"pagerank_query_error: {e}")

                try:
                    sim = s.run(
                        "MATCH (m:Method) WHERE m.similarity_community IS NOT NULL RETURN count(m) AS c"
                    ).single()
                    report["similarity_community_methods"] = int(sim["c"]) if sim else 0
                except Exception as e:
                    errors = report.get("errors")
                    if isinstance(errors, list):
                        errors.append(f"sim_query_error: {e}")

                try:
                    emb = s.run(
                        f"MATCH (m:Method) WHERE m.{EMBEDDING_PROPERTY} IS NOT NULL RETURN count(m) AS c"
                    ).single()
                    report["embeddings_methods"] = int(emb["c"]) if emb else 0
                except Exception as e:
                    errors = report.get("errors")
                    if isinstance(errors, list):
                        errors.append(f"emb_query_error: {e}")

                try:
                    gv = s.run("CALL gds.version() YIELD version RETURN version").single()
                    report["gds_version"] = gv["version"] if gv else None
                except Exception as e:
                    errors = report.get("errors")
                    if isinstance(errors, list):
                        errors.append(f"gds_version_error: {e}")

                # Dependency state summary
                try:
                    rec = s.run(
                        "MATCH (e:ExternalDependency) RETURN count(e) AS total, count{e.version IS NOT NULL} AS with_version"
                    ).single()
                    if rec:
                        report["external_dependencies"] = int(rec["total"] or 0)
                        report["external_with_version"] = int(rec["with_version"] or 0)
                except Exception as e:
                    errors = report.get("errors")
                    if isinstance(errors, list):
                        errors.append(f"external_dep_summary_error: {e}")
    except Exception as e:
        errors = report.get("errors")
        if isinstance(errors, list):
            errors.append(f"connection_error: {e}")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
