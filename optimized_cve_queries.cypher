// ===================================================================
// OPTIMIZED CVE-TO-DEVELOPER QUERIES
// These queries are optimized for performance with proper indexes
// ===================================================================

// 🚀 FASTEST: Find high-risk CVE-to-Developer connections
// Optimized with early filtering and limits
MATCH (cve:CVE)
WHERE cve.cvss_score >= 7.0
WITH cve ORDER BY cve.cvss_score DESC LIMIT 50

MATCH (cve)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(f:File)
WITH cve, dep, collect(DISTINCT f)[0..10] as files
UNWIND files as f

MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
WITH cve, dep, f, dev, count(DISTINCT c) as commit_count
WHERE commit_count >= 2

RETURN cve.id as vulnerability,
       cve.cvss_score as severity,
       dep.package as affected_dependency,
       f.path as file_path,
       dev.name as developer,
       dev.email as email,
       commit_count as expertise_level
ORDER BY cve.cvss_score DESC, commit_count DESC
LIMIT 100;

// 🎯 EFFICIENT: CVE impact by developer expertise
// Groups results by developer for better insights
MATCH (cve:CVE)
WHERE cve.cvss_score >= 6.0
WITH cve ORDER BY cve.cvss_score DESC LIMIT 100

MATCH (cve)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(f:File)
MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)

WITH dev, 
     collect(DISTINCT cve.id) as cves,
     collect(DISTINCT dep.package) as dependencies,
     collect(DISTINCT f.path) as files,
     max(cve.cvss_score) as max_severity,
     count(DISTINCT c) as total_commits

WHERE total_commits >= 3

RETURN dev.name as developer,
       dev.email as email,
       size(cves) as vulnerabilities_count,
       size(dependencies) as affected_dependencies,
       size(files) as files_at_risk,
       total_commits as expertise_level,
       max_severity as highest_cvss_score,
       cves[0..5] as sample_cves
ORDER BY max_severity DESC, vulnerabilities_count DESC
LIMIT 50;

// 📊 SUMMARY: CVE exposure by file complexity
// Identifies high-risk files that are complex AND have vulnerabilities
MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(f:File)
WHERE cve.cvss_score >= 7.0 
  AND f.total_lines > 100
  AND f.method_count > 5

OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
WHERE c.date > datetime() - duration('P365D')

WITH f, 
     count(DISTINCT cve) as vulnerability_count,
     max(cve.cvss_score) as max_cvss,
     collect(DISTINCT dep.package) as dependencies,
     count(DISTINCT dev) as developer_count,
     count(DISTINCT c) as recent_changes

RETURN f.path as file_path,
       f.total_lines as lines_of_code,
       f.method_count as method_count,
       vulnerability_count,
       max_cvss as highest_severity,
       developer_count as developers_involved,
       recent_changes as changes_last_year,
       (f.total_lines * vulnerability_count + max_cvss * 10) as risk_score,
       dependencies[0..3] as sample_dependencies
ORDER BY risk_score DESC
LIMIT 25;

// ⚡ LIGHTNING FAST: Critical path summary
// Minimal data for dashboard/alerting
MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(f:File)
WHERE cve.cvss_score >= 8.0

OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
WHERE c.date > datetime() - duration('P90D')

WITH cve.id as cve_id,
     cve.cvss_score as severity,
     count(DISTINCT f) as files_affected,
     count(DISTINCT dev) as developers_involved

WHERE files_affected > 0

RETURN cve_id, severity, files_affected, developers_involved
ORDER BY severity DESC, files_affected DESC;

// 🔍 DEEP DIVE: Specific CVE analysis
// Use this template and replace CVE-2022-28291 with your target CVE
MATCH (cve:CVE {id: "CVE-2022-28291"})-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(f:File)

OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)

WITH f, dep, dev, count(DISTINCT c) as commit_count, max(c.date) as latest_commit
WITH f, dep, 
     collect(DISTINCT {
       developer: dev.name,
       email: dev.email,
       commits: commit_count,
       latest_commit: latest_commit
     }) as developers

RETURN f.path as vulnerable_file,
       f.total_lines as complexity,
       dep.package as dependency,
       size(developers) as developer_count,
       [d IN developers WHERE d.commits >= 3] as experts,
       [d IN developers WHERE d.latest_commit > datetime() - duration('P90D')] as recent_contributors
ORDER BY f.total_lines DESC; 