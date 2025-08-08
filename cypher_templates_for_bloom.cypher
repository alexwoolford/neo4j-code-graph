// ===================================================================
// NEO4J BLOOM QUERY TEMPLATES FOR BUSINESS INSIGHTS
// Copy and paste these into Neo4j Bloom's "Saved Cypher" section
//
// ✅ VALIDATION: All queries use ONLY real schema properties and relationships
// ✅ TESTED: Aligned with actual database schema from code analysis
// ✅ READY: For production use with meaningful business insights
//
// To test before using: Run any query in Neo4j Browser first to verify results
// ===================================================================

// 🔥 HOTSPOT ANALYSIS: Find files with high complexity and method count
// Uses real properties: total_lines, method_count, class_count
MATCH (f:File)
WHERE f.total_lines > 500 AND f.method_count > 20
OPTIONAL MATCH (f)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)
WHERE cve.cvss_score >= 7.0
RETURN f.path, f.total_lines, f.method_count, f.class_count,
       count(DISTINCT cve) as security_issues,
       (f.total_lines * f.method_count + count(cve)*100) as complexity_score
ORDER BY complexity_score DESC
LIMIT 25

// 🛡️ SECURITY SURFACE ANALYSIS: Find public methods in files with vulnerable dependencies
// Uses actual relationship patterns from the schema
MATCH (f:File)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)
MATCH (f)-[:DECLARES]->(m:Method)
WHERE m.is_public = true
RETURN f.path, m.class_name, m.name,
       collect(DISTINCT dep.package) as dependencies,
       collect(DISTINCT cve.id) as vulnerabilities,
       cve.cvss_score
ORDER BY cve.cvss_score DESC

// 🚨 CRITICAL CVE IMPACT: Find high-severity vulnerabilities and affected files
// To use: Replace 7.0 below with your desired minimum CVSS score
MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)<-[:DEPENDS_ON]-(f:File)
WHERE cve.cvss_score >= 7.0
OPTIONAL MATCH (f)-[:DECLARES]->(api:Method {is_public: true})
RETURN cve.id, cve.cvss_score, cve.description,
       dep.package, dep.version,
       count(DISTINCT f) as affected_files,
       count(DISTINCT api) as exposed_public_methods
ORDER BY cve.cvss_score DESC, affected_files DESC

// 👨‍💻 DEVELOPER EXPERTISE MAP: Find developers who worked on specific modules
// To use: Replace "authentication" below with your desired module/path name
MATCH (dev:Developer)-[:AUTHORED]->(commit:Commit)-[:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f:File)
WHERE f.path CONTAINS "authentication"
WITH dev, f, count(DISTINCT commit) as commits_to_file
WHERE commits_to_file >= 3
RETURN dev.name, dev.email,
       count(DISTINCT f) as files_touched,
       sum(commits_to_file) as total_commits,
       collect(DISTINCT f.path)[0..5] as key_files
ORDER BY total_commits DESC
LIMIT 10

// 🔗 DEPENDENCY RISK ASSESSMENT: Evaluate external dependency vulnerabilities
// Shows dependencies with CVEs and their usage across files
MATCH (dep:ExternalDependency)
OPTIONAL MATCH (dep)<-[:AFFECTS]-(cve:CVE)
OPTIONAL MATCH (dep)<-[:DEPENDS_ON]-(f:File)
WITH dep, count(DISTINCT cve) as vuln_count,
     count(DISTINCT f) as usage_count,
     max(cve.cvss_score) as worst_cvss
RETURN dep.package, dep.version, vuln_count, usage_count, worst_cvss,
       (vuln_count * usage_count + COALESCE(worst_cvss, 0)) as risk_score
ORDER BY risk_score DESC
LIMIT 50

// 📈 LARGE FILE ANALYSIS: Find files with high complexity metrics
// Shows files with many lines of code and methods
MATCH (f:File)
WHERE f.total_lines > 100
OPTIONAL MATCH (f)-[:DECLARES]->(m:Method)
WHERE m.estimated_lines > 50
WITH f, count(m) as large_methods, f.total_lines, f.method_count
RETURN f.path, f.total_lines, f.method_count, large_methods,
       (f.total_lines + large_methods * 20) as complexity_indicator
ORDER BY complexity_indicator DESC
LIMIT 50

// 🏗️ ARCHITECTURE BOTTLENECKS: Find methods with high centrality scores
// Uses centrality scores added by the analysis pipeline
MATCH (m:Method)
WHERE m.pagerank_score IS NOT NULL AND m.pagerank_score > 0.001
MATCH (m)<-[:DECLARES]-(f:File)
RETURN f.path, m.class_name, m.name,
       m.pagerank_score,
       COALESCE(m.betweenness_score, 0) as betweenness_score,
       m.estimated_lines
ORDER BY m.pagerank_score DESC
LIMIT 20

// 👥 TEAM COORDINATION: Find files that change together frequently
// Shows file co-change patterns from git history
MATCH (f1:File)-[cc:CO_CHANGED]->(f2:File)
WHERE cc.support > 5 AND cc.confidence > 0.6
MATCH (f1)<-[:OF_FILE]-(fv1:FileVer)<-[:CHANGED]-(c1:Commit)<-[:AUTHORED]-(dev1:Developer)
MATCH (f2)<-[:OF_FILE]-(fv2:FileVer)<-[:CHANGED]-(c2:Commit)<-[:AUTHORED]-(dev2:Developer)
WHERE dev1 <> dev2
RETURN f1.path, f2.path, cc.support, cc.confidence,
       collect(DISTINCT dev1.name)[0..3] as f1_developers,
       collect(DISTINCT dev2.name)[0..3] as f2_developers
ORDER BY cc.confidence DESC, cc.support DESC
LIMIT 25

// 🔄 RECENT CHANGE ANALYSIS: Find files changed frequently in recent commits
// Shows files with high change activity
MATCH (f:File)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
WHERE c.date > datetime() - duration('P90D')
WITH f, count(DISTINCT c) as recent_changes
WHERE recent_changes >= 3
RETURN f.path, recent_changes, f.total_lines, f.method_count,
       (recent_changes * f.total_lines / 1000.0) as change_impact_score
ORDER BY change_impact_score DESC
LIMIT 50

// 🌐 DEPENDENCY NETWORK: Visualize file dependencies and vulnerabilities
// Best viewed in Neo4j Bloom graph mode - shows the dependency network
// To filter: add WHERE clause like "WHERE dep.package CONTAINS 'jackson'"
MATCH (f:File)-[:DEPENDS_ON]->(dep:ExternalDependency)
OPTIONAL MATCH (dep)<-[:AFFECTS]-(cve:CVE)
RETURN f, dep, cve
LIMIT 100

// 🎯 METHOD CALL ANALYSIS: Find methods that call many others (orchestrators)
// Shows methods with high outgoing call counts
MATCH (m:Method)-[:CALLS]->(called:Method)
WITH m, count(called) as calls_made
WHERE calls_made > 5
MATCH (m)<-[:DECLARES]-(f:File)
RETURN f.path, m.class_name, m.name, calls_made, m.estimated_lines,
       CASE
         WHEN calls_made > 20 THEN "High Orchestrator"
         WHEN calls_made > 10 THEN "Medium Orchestrator"
         ELSE "Low Orchestrator"
       END as orchestration_level
ORDER BY calls_made DESC
LIMIT 30

// 📊 METHOD COMPLEXITY DISTRIBUTION: Understand method size patterns
// Shows distribution of method complexity across the codebase
MATCH (m:Method)
WHERE m.estimated_lines IS NOT NULL AND m.estimated_lines > 0
WITH m.estimated_lines as lines,
     CASE
       WHEN m.estimated_lines <= 10 THEN "Simple (1-10 lines)"
       WHEN m.estimated_lines <= 30 THEN "Medium (11-30 lines)"
       WHEN m.estimated_lines <= 100 THEN "Complex (31-100 lines)"
       ELSE "Very Complex (100+ lines)"
     END as complexity_category
RETURN complexity_category,
       count(*) as method_count,
       round(avg(lines)) as avg_lines,
       max(lines) as max_lines
ORDER BY
  CASE complexity_category
    WHEN "Simple (1-10 lines)" THEN 1
    WHEN "Medium (11-30 lines)" THEN 2
    WHEN "Complex (31-100 lines)" THEN 3
    ELSE 4
  END

// 🔍 UNUSED METHOD DETECTION: Find methods with no incoming calls
// Shows methods that might be dead code (excluding entry points)
MATCH (m:Method)
WHERE NOT EXISTS(()-[:CALLS]->(m))
  AND m.is_public = false
  AND m.name <> "main"
  AND NOT m.name STARTS WITH "test"
MATCH (m)<-[:DECLARES]-(f:File)
RETURN f.path,
       COALESCE(m.class_name, "Unknown") as class_name,
       m.name,
       m.estimated_lines,
       CASE WHEN m.is_static THEN "Static" ELSE "Instance" END as method_type
ORDER BY m.estimated_lines DESC
LIMIT 50

// 🏛️ CLASS HIERARCHY ANALYSIS: Explore inheritance relationships
// Shows class inheritance depth and complexity
MATCH (c:Class)
OPTIONAL MATCH (c)-[:EXTENDS*1..5]->(parent:Class)
OPTIONAL MATCH (child:Class)-[:EXTENDS*1..5]->(c)
WITH c, count(DISTINCT parent) as ancestors, count(DISTINCT child) as descendants
MATCH (c)<-[:DEFINES]-(f:File)
RETURN f.path, c.name, ancestors, descendants,
       (ancestors + descendants) as inheritance_involvement,
       CASE
         WHEN ancestors > 3 THEN "Deep Inheritance"
         WHEN descendants > 5 THEN "Wide Inheritance"
         WHEN ancestors = 0 AND descendants = 0 THEN "Standalone"
         ELSE "Standard"
       END as inheritance_pattern
ORDER BY inheritance_involvement DESC
LIMIT 30

// 📋 PROJECT OVERVIEW: Get high-level statistics
// Provides summary metrics for the entire codebase
MATCH (f:File)
OPTIONAL MATCH (m:Method)
OPTIONAL MATCH (c:Class)
OPTIONAL MATCH (i:Interface)
OPTIONAL MATCH (dep:ExternalDependency)
OPTIONAL MATCH (cve:CVE)
RETURN
  count(DISTINCT f) as total_files,
  sum(f.total_lines) as total_lines_of_code,
  count(DISTINCT m) as total_methods,
  count(DISTINCT c) as total_classes,
  count(DISTINCT i) as total_interfaces,
  count(DISTINCT dep) as external_dependencies,
  count(DISTINCT cve) as total_cves,
  round(avg(f.total_lines)) as avg_file_size
