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
