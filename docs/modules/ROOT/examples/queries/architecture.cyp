// tag::refactor_candidates[]
MATCH (f:File)
WHERE f.total_lines > 500 AND f.method_count > 20
OPTIONAL MATCH (f)-[:IMPORTS]->(i:Import)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)
WHERE cve.cvss_score >= 7.0
RETURN f.path, f.total_lines, f.method_count, f.class_count,
       count(DISTINCT cve) as security_issues,
       (f.total_lines * f.method_count + count(cve)*100) as priority_score
ORDER BY priority_score DESC
LIMIT 25
// end::refactor_candidates[]

// tag::architectural_bottlenecks[]
MATCH (m:Method)
WHERE m.pagerank_score IS NOT NULL AND m.pagerank_score > 0.001
MATCH (m)<-[:DECLARES]-(f:File)
RETURN f.path, m.class_name, m.name,
       m.pagerank_score as importance,
       m.estimated_lines as complexity
ORDER BY m.pagerank_score DESC
LIMIT 20
// end::architectural_bottlenecks[]

// tag::directory_call_cycles[]
// Cross-directory call cycles using existing schema (Directory, File, Method, CALLS)
MATCH (da:Directory)-[:CONTAINS]->(a:File),
      (db:Directory)-[:CONTAINS]->(b:File)
WHERE da.path <> db.path
MATCH (a)-[:DECLARES]->(:Method)-[:CALLS]->(:Method)<-[:DECLARES]-(b)
WITH da.path AS d1, db.path AS d2, count(*) AS calls
WITH collect({d1:d1,d2:d2,calls:calls}) AS pairs
UNWIND pairs AS x
WITH x, [y IN pairs WHERE y.d1 = x.d2 AND y.d2 = x.d1] AS back
WHERE size(back) > 0 AND x.d1 < x.d2
RETURN x.d1 AS dir1, x.d2 AS dir2, x.calls AS calls12, back[0].calls AS calls21
ORDER BY (x.calls + back[0].calls) DESC
LIMIT 25
// end::directory_call_cycles[]
