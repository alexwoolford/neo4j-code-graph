#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any


def main() -> None:
    from src.utils.common import create_neo4j_driver, get_neo4j_config

    uri, user, pwd, db = get_neo4j_config()
    out: dict[str, Any] = {"uri": uri, "database": db, "results": {}, "errors": {}}

    queries: dict[str, str] = {
        "cochange_pairs": (
            "MATCH (f1:File)-[cc:CO_CHANGED]->(f2:File)\n"
            "WHERE cc.support >= 5 AND cc.confidence >= 0.6\n"
            "RETURN f1.path AS f1, f2.path AS f2, cc.support AS support, cc.confidence AS confidence\n"
            "ORDER BY confidence DESC, support DESC\nLIMIT 25"
        ),
        "api_vuln": (
            "MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)\n"
            "MATCH (f)-[:DECLARES]->(m:Method)\n"
            "WHERE m.is_public = true AND cve.cvss_score >= 7.0\n"
            "RETURN f.path, m.class_name, m.name, cve.id, cve.cvss_score\n"
            "ORDER BY cve.cvss_score DESC"
        ),
        "dep_risk_summary": (
            "MATCH (dep:ExternalDependency)\n"
            "OPTIONAL MATCH (dep)<-[:AFFECTS]-(cve:CVE)\n"
            "OPTIONAL MATCH (dep)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)\n"
            "RETURN dep.package, dep.version,\n"
            "       count(DISTINCT cve) as vulnerabilities,\n"
            "       count(DISTINCT f) as files_using_it,\n"
            "       max(cve.cvss_score) as worst_cvss_score\n"
            "ORDER BY vulnerabilities DESC, files_using_it DESC"
        ),
        "refactor_candidates": (
            "MATCH (f:File)\n"
            "WHERE f.total_lines > 500 AND f.method_count > 20\n"
            "OPTIONAL MATCH (f)-[:IMPORTS]->(i:Import)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)\n"
            "WHERE cve.cvss_score >= 7.0\n"
            "RETURN f.path, f.total_lines, f.method_count, f.class_count,\n"
            "       count(DISTINCT cve) as security_issues,\n"
            "       (f.total_lines * f.method_count + count(cve)*100) as priority_score\n"
            "ORDER BY priority_score DESC\nLIMIT 25"
        ),
        "architectural_bottlenecks": (
            "MATCH (m:Method)\n"
            "WHERE m.pagerank_score IS NOT NULL AND m.pagerank_score > 0.001\n"
            "MATCH (m)<-[:DECLARES]-(f:File)\n"
            "RETURN f.path, m.class_name, m.name, m.pagerank_score as importance, m.estimated_lines as complexity\n"
            "ORDER BY m.pagerank_score DESC\nLIMIT 20"
        ),
        "top_central_methods": (
            "MATCH (m:Method) WHERE m.pagerank_score IS NOT NULL\n"
            "RETURN m.method_signature AS method, m.class_name AS class, m.file AS file, m.pagerank_score AS score\n"
            "ORDER BY score DESC, file, class, method\nLIMIT 25"
        ),
        "validate_louvain": (
            "MATCH (m:Method) WHERE m.similarity_community IS NOT NULL\n"
            "RETURN m.similarity_community AS community, count(*) AS members\n"
            "ORDER BY members DESC, community\nLIMIT 10"
        ),
        "blast_radius": (
            "MATCH (m:Method) WHERE m.pagerank_score IS NOT NULL\n"
            "OPTIONAL MATCH (caller:Method)-[:CALLS]->(m)\n"
            "OPTIONAL MATCH (caller)<-[:CONTAINS_METHOD]-(callerClass:Class)<-[:CONTAINS]-(callerPkg:Package)\n"
            "WITH m, count(DISTINCT caller) AS callers, count(DISTINCT callerPkg.name) AS caller_packages\n"
            "RETURN m.method_signature AS method, m.pagerank_score AS centrality, callers, caller_packages\n"
            "ORDER BY centrality DESC, caller_packages DESC, callers DESC\nLIMIT 25"
        ),
        "community_modules": (
            "MATCH (m:Method) WHERE m.similarity_community IS NOT NULL\n"
            "OPTIONAL MATCH (m)<-[:CONTAINS_METHOD]-(c:Class)<-[:CONTAINS]-(p:Package)\n"
            "WITH m.similarity_community AS community, count(*) AS members, count(DISTINCT c) AS classes, count(DISTINCT p) AS packages\n"
            "RETURN community, members, classes, packages\n"
            "ORDER BY members DESC, packages ASC\nLIMIT 20"
        ),
        "fractured_classes": (
            "MATCH (cls:Class)-[:CONTAINS_METHOD]->(m:Method) WHERE m.similarity_community IS NOT NULL\n"
            "WITH cls, count(DISTINCT m.similarity_community) AS distinct_communities, count(m) AS methods, apoc.coll.toSet(collect(DISTINCT m.similarity_community))[..5] AS sample\n"
            "WHERE distinct_communities >= 2\n"
            "RETURN cls.name AS class, cls.file AS file, methods, distinct_communities, sample AS communities\n"
            "ORDER BY distinct_communities DESC, methods DESC\nLIMIT 25"
        ),
        "package_risk": (
            "MATCH (p:Package)-[:CONTAINS]->(:Class)<-[:DEFINES]-(f:File)\n"
            "MATCH (c:Commit)-[:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f)\n"
            "WITH p, count(c) AS churn\n"
            "MATCH (p)-[:CONTAINS]->(:Class)-[:CONTAINS_METHOD]->(m:Method)\n"
            "MATCH (m)-[:CALLS]->(m2:Method)\n"
            "MATCH (q:Package)-[:CONTAINS]->(:Class)-[:CONTAINS_METHOD]->(m2)\n"
            "WHERE p <> q\n"
            "WITH p, churn, count(DISTINCT q) AS fanoutPkgs\n"
            "RETURN p.name AS package, churn, fanoutPkgs, churn*fanoutPkgs AS riskScore\n"
            "ORDER BY riskScore DESC\nLIMIT 15"
        ),
        "implements": (
            "MATCH (i:Interface {name: $interface}) MATCH (c:Class)-[:IMPLEMENTS]->(i)\n"
            "RETURN i.name AS interface, c.name AS class, c.file AS file\n"
            "ORDER BY interface, class"
        ),
        "interfaces_without_impl": (
            "MATCH (i:Interface) WHERE NOT ( (:Class)-[:IMPLEMENTS]->(i) )\n"
            "RETURN i.name AS interface, i.file AS file\n"
            "ORDER BY interface"
        ),
        "experts_for_module": (
            "MATCH (dev:Developer)-[:AUTHORED]->(commit:Commit)-[:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f:File)\n"
            "WHERE f.path CONTAINS $module\n"
            "WITH dev, f, count(DISTINCT commit) as commits_to_file\n"
            "WHERE commits_to_file >= 3\n"
            "RETURN dev.name, dev.email, count(DISTINCT f) as files_touched, sum(commits_to_file) as total_commits\n"
            "ORDER BY total_commits DESC\nLIMIT 10"
        ),
        "most_changed_files": (
            "MATCH (c:Commit)-[r:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f:File)\n"
            "WITH f.path AS path, count(*) AS changes, sum(coalesce(r.additions, 0)) AS adds, sum(coalesce(r.deletions, 0)) AS dels, sum(coalesce(r.additions, 0) + coalesce(r.deletions, 0)) AS churn\n"
            "RETURN path, changes, adds, dels, churn\n"
            "ORDER BY churn DESC\nLIMIT 25"
        ),
        "docs_methods": (
            "MATCH (m:Method)-[:HAS_DOC]->(d:Doc)\n"
            "RETURN m.method_signature AS method, d.text AS doc, d.start_line AS start, d.end_line AS end\n"
            "ORDER BY method, start"
        ),
        "docs_classes": (
            "MATCH (c:Class)-[:HAS_DOC]->(d:Doc)\n"
            "RETURN c.name AS class, c.file AS file, d.text AS doc, d.start_line AS start\n"
            "ORDER BY file, class, start"
        ),
        "top_complex_methods": (
            "MATCH (m:Method) WHERE m.cyclomatic_complexity IS NOT NULL\n"
            "RETURN m.name AS method, m.file AS file, m.cyclomatic_complexity AS cc\n"
            "ORDER BY cc DESC, file, method\nLIMIT 25"
        ),
        "deprecated_and_callers": (
            "MATCH (d:Method {deprecated:true}) OPTIONAL MATCH (caller:Method)-[:CALLS]->(d)\n"
            "RETURN d.class_name AS class, d.name AS method, d.deprecated_since AS since, count(caller) AS callers\n"
            "ORDER BY callers DESC, class, method"
        ),
        "release_risk": (
            "MATCH (f:File)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)\n"
            "WHERE c.date > datetime() - duration('P7D')\n"
            "WITH f, count(c) as recent_changes\n"
            "WHERE recent_changes > 0\n"
            "OPTIONAL MATCH (f)-[:IMPORTS]->(i:Import)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)\n"
            "WHERE cve.cvss_score >= 7.0\n"
            "OPTIONAL MATCH (f)-[:DECLARES]->(m:Method {is_public: true})\n"
            "RETURN f.path as path, recent_changes, count(DISTINCT cve) as security_risks, count(DISTINCT m) as public_api_methods,\n"
            "       CASE\n"
            "         WHEN count(DISTINCT cve) > 0 AND count(DISTINCT m) > 0 THEN 'HIGH RISK'\n"
            "         WHEN count(DISTINCT cve) > 0 OR recent_changes > 10 THEN 'MEDIUM RISK'\n"
            "         ELSE 'LOW RISK'\n"
            "       END as release_risk_level\n"
            "ORDER BY recent_changes DESC"
        ),
    }

    params: dict[str, dict[str, object]] = {
        "implements": {"interface": "Runnable"},
        "experts_for_module": {"module": "src/"},
    }

    with create_neo4j_driver(uri, user, pwd) as driver:
        with driver.session(database=db) as s:
            for key, q in queries.items():
                p = params.get(key, {})
                try:
                    data = s.run(q, **p).data()
                    out["results"][key] = {"rows": len(data), "sample": data[:5]}
                except Exception as e:
                    out["errors"][key] = str(e)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
