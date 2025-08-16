// tag::tech_health_summary[]
MATCH (f:File)
OPTIONAL MATCH (f)-[:DECLARES]->(m:Method)
WITH count(DISTINCT f) as total_files,
     sum(f.total_lines) as total_lines_of_code,
     count(DISTINCT m) as total_methods,
     sum(CASE WHEN m.estimated_lines > 100 THEN 1 ELSE 0 END) as complex_methods

OPTIONAL MATCH (cve:CVE)
WHERE cve.cvss_score >= 7.0

RETURN total_files, total_lines_of_code, total_methods, complex_methods,
       count(DISTINCT cve) as high_severity_vulnerabilities,
       round(100 - (complex_methods * 100.0 / total_methods)) as maintainability_score
// end::tech_health_summary[]

// tag::release_risk_assessment[]
MATCH (f:File)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
WHERE c.date > datetime() - duration('P7D')
WITH f, count(c) as recent_changes
WHERE recent_changes > 0
OPTIONAL MATCH (f)-[:IMPORTS]->(i:Import)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)
WHERE cve.cvss_score >= 7.0
OPTIONAL MATCH (f)-[:DECLARES]->(m:Method {is_public: true})
RETURN f.path as path, recent_changes,
       count(DISTINCT cve) as security_risks,
       count(DISTINCT m) as public_api_methods,
       CASE
         WHEN count(DISTINCT cve) > 0 AND count(DISTINCT m) > 0 THEN "HIGH RISK"
         WHEN count(DISTINCT cve) > 0 OR recent_changes > 10 THEN "MEDIUM RISK"
         ELSE "LOW RISK"
       END as release_risk_level
ORDER BY recent_changes DESC
// end::release_risk_assessment[]
