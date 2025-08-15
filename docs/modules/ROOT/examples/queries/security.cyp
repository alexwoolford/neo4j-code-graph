// tag::api_vulnerable_dependencies[]
MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
MATCH (f)-[:DECLARES]->(m:Method)
WHERE m.is_public = true AND cve.cvss_score >= 7.0
RETURN f.path, m.class_name, m.name, cve.id, cve.cvss_score
ORDER BY cve.cvss_score DESC
// end::api_vulnerable_dependencies[]

// tag::dependency_risk_summary[]
MATCH (dep:ExternalDependency)
OPTIONAL MATCH (dep)<-[:AFFECTS]-(cve:CVE)
OPTIONAL MATCH (dep)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File)
RETURN dep.package, dep.version,
       count(DISTINCT cve) as vulnerabilities,
       count(DISTINCT f) as files_using_it,
       max(cve.cvss_score) as worst_cvss_score
ORDER BY vulnerabilities DESC, files_using_it DESC
// end::dependency_risk_summary[]
