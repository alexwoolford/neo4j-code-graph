# Business Use Cases & Query Examples

This guide shows how to use Neo4j Code Graph for common business scenarios. Each example includes the business context, the Cypher query, and how to interpret results.

## 🚨 Security & Risk Management

### Log4j Vulnerability Response
**Scenario:** A critical vulnerability is discovered in Log4j. You need to immediately understand your exposure.

**Business Question:** "Which of our customer-facing APIs are affected?"

```cypher
// Find all public APIs that could be affected by Log4j vulnerability
MATCH (cve:CVE {id: "CVE-2021-44228"})-[:AFFECTS]->(vuln_lib)
MATCH path = (api:Method {is_public: true})-[:CALLS*1..5]->(internal:Method)-[:USES]->(vuln_lib)
RETURN DISTINCT 
  api.class + "." + api.name as exposed_endpoint,
  length(path) as vulnerability_depth,
  "CRITICAL - Customer data at risk" as impact_level
ORDER BY vulnerability_depth ASC
```

**How to use results:**
- `vulnerability_depth = 1`: Direct exposure, patch immediately
- `vulnerability_depth > 3`: Indirect exposure, assess risk level
- Share list with Product team to understand customer impact

### Dependency License Compliance
**Scenario:** Legal team needs to audit all open-source dependencies for license compliance.

```cypher
MATCH (dep:ExternalDependency)
MATCH (dep)<-[:DEPENDS_ON]-(f:File)
RETURN dep.package, dep.version, dep.license,
       count(DISTINCT f) as usage_count,
       collect(DISTINCT f.path)[0..3] as sample_usage
ORDER BY usage_count DESC
```

## 🏗️ Architecture & Technical Debt

### Refactoring Priority Matrix
**Scenario:** Limited budget for technical debt. Which components give maximum ROI?

**Business Question:** "What 20% of our code impacts 80% of the system?"

```cypher
// Find high-impact components using PageRank + complexity
MATCH (m:Method)
WHERE m.pagerank_score IS NOT NULL 
  AND m.estimated_lines > 20
WITH m, (m.pagerank_score * m.estimated_lines) as impact_score
MATCH (m)<-[:DECLARES]-(f:File)
RETURN f.path, m.class, m.name,
       m.pagerank_score as system_importance,
       m.estimated_lines as complexity,
       impact_score,
       "High ROI refactoring target" as recommendation
ORDER BY impact_score DESC
LIMIT 20
```

**Executive Summary Template:**
> "These 20 methods represent architectural bottlenecks. Refactoring them will improve system maintainability by an estimated 40% while reducing 60% of change-related bugs."

### Conway's Law Validation
**Scenario:** Team structure might not match system architecture.

```cypher
// Find components that span multiple team boundaries
MATCH (f1:File)-[cc:CO_CHANGED]->(f2:File)
WHERE cc.confidence > 0.8
MATCH (f1)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(:Commit)<-[:AUTHORED]-(dev1:Developer)
MATCH (f2)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(:Commit)<-[:AUTHORED]-(dev2:Developer)
WHERE dev1.team <> dev2.team  // Assuming team info is available
RETURN f1.path, f2.path, cc.confidence,
       dev1.team, dev2.team,
       "Cross-team coordination required" as issue
```

## 👥 Team Productivity & Planning

### Sprint Planning Support  
**Scenario:** Product wants to add a feature to the payment system. Which developers should be involved?

```cypher
// Find payment system experts
MATCH (dev:Developer)-[:AUTHORED]->(commit:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f:File)
WHERE f.path CONTAINS "payment" OR f.path CONTAINS "billing"
WITH dev, count(commit) as payment_commits
WHERE payment_commits >= 5
MATCH (dev)-[:AUTHORED]->(recent:Commit)
WHERE recent.date > datetime() - duration('P180D')  // Active in last 6 months
RETURN dev.name, dev.email, payment_commits,
       count(recent) as recent_activity,
       "Payment system expert" as expertise_level
ORDER BY payment_commits DESC, recent_activity DESC
```

### Code Review Assignment
**Scenario:** Automatically assign the best reviewer for a pull request.

```cypher
// Find experts for files in a PR (parameterized query)
UNWIND $changed_files as file_path
MATCH (dev:Developer)-[:AUTHORED]->(commit:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f:File {path: file_path})
WITH file_path, dev, count(commit) as expertise_level
WHERE expertise_level >= 3
RETURN file_path, 
       collect({developer: dev.name, expertise: expertise_level})[0..2] as suggested_reviewers
```

### Technical Onboarding
**Scenario:** New team member needs to understand the codebase architecture.

```cypher
// Create onboarding path - most important classes to understand first
MATCH (c:Class)
WHERE EXISTS((c)-[:EXTENDS|IMPLEMENTS]->()) OR EXISTS(()-[:EXTENDS|IMPLEMENTS]->(c))
OPTIONAL MATCH (c)<-[:DECLARES]-(f:File)
OPTIONAL MATCH (c)-[:DECLARES]->(m:Method)
WHERE m.pagerank_score > 0.001
RETURN c.name, f.path,
       count(m) as important_methods,
       CASE 
         WHEN EXISTS((c)-[:EXTENDS|IMPLEMENTS]->()) THEN "Core abstraction - start here"
         WHEN count(m) > 5 THEN "Complex component - understand after basics"
         ELSE "Supporting component"
       END as learning_priority
ORDER BY important_methods DESC
```

## 📊 Executive Reporting

### Monthly Technical Health Report

```cypher
// Technical debt summary for executive dashboard
MATCH (f:File)
OPTIONAL MATCH (f)-[:DECLARES]->(m:Method)
WITH f, 
     count(m) as method_count,
     sum(m.estimated_lines) as total_complexity,
     sum(CASE WHEN m.estimated_lines > 100 THEN 1 ELSE 0 END) as high_complexity_methods

OPTIONAL MATCH (f)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(recent:Commit)
WHERE recent.date > datetime() - duration('P30D')

OPTIONAL MATCH (f)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)
WHERE cve.cvss_score >= 7.0

RETURN 
  "Technical Health Summary" as metric_category,
  count(DISTINCT f) as total_files,
  sum(method_count) as total_methods,
  sum(total_complexity) as total_lines_of_code,
  sum(high_complexity_methods) as complex_methods,
  count(DISTINCT recent) as files_changed_this_month,
  count(DISTINCT cve) as high_severity_vulnerabilities,
  
  // Health score calculation (0-100)
  toInteger(100 - (
    (sum(high_complexity_methods) * 1.0 / sum(method_count) * 30) +
    (count(DISTINCT cve) * 1.0 / count(DISTINCT f) * 40) +
    (count(DISTINCT recent) * 1.0 / count(DISTINCT f) * 30)
  )) as technical_health_score
```

### Release Risk Assessment

```cypher
// Pre-release risk assessment
MATCH (f:File)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(c:Commit)
WHERE c.date > datetime() - duration('P7D')  // Last week's changes

WITH f, count(c) as recent_changes
WHERE recent_changes > 0

OPTIONAL MATCH (f)-[:DEPENDS_ON]->(dep:ExternalDependency)<-[:AFFECTS]-(cve:CVE)
WHERE cve.cvss_score >= 7.0

OPTIONAL MATCH (f)-[:DECLARES]->(m:Method {is_public: true})

RETURN 
  f.path,
  recent_changes,
  count(DISTINCT cve) as security_risks,
  count(DISTINCT m) as public_api_methods,
  CASE 
    WHEN count(DISTINCT cve) > 0 AND count(DISTINCT m) > 0 THEN "HIGH RISK"
    WHEN count(DISTINCT cve) > 0 OR recent_changes > 10 THEN "MEDIUM RISK"
    ELSE "LOW RISK"
  END as release_risk_level
ORDER BY 
  CASE 
    WHEN count(DISTINCT cve) > 0 AND count(DISTINCT m) > 0 THEN 1
    WHEN count(DISTINCT cve) > 0 OR recent_changes > 10 THEN 2
    ELSE 3
  END,
  recent_changes DESC
```

## 🔧 Operations & Monitoring

### Change Impact Analysis
**Scenario:** A critical bug needs to be fixed. What else might be affected?

```cypher
// Find all components that might be impacted by changing a specific method
MATCH (target:Method {name: $method_name, class: $class_name})
MATCH (caller:Method)-[:CALLS*1..3]->(target)
MATCH (caller)<-[:DECLARES]-(f:File)
RETURN DISTINCT f.path, caller.class, caller.name,
       "May be affected by changes to " + target.class + "." + target.name as impact_note
ORDER BY f.path
```

### Performance Hotspot Investigation
**Scenario:** Application is slow. Where should we optimize first?

```cypher
// Find methods that are likely performance bottlenecks
MATCH (m:Method)
WHERE m.estimated_lines > 50  // Complex methods
OPTIONAL MATCH (caller:Method)-[:CALLS]->(m)
WITH m, count(caller) as call_frequency
WHERE call_frequency > 10  // Frequently called
MATCH (m)<-[:DECLARES]-(f:File)
RETURN f.path, m.class, m.name, 
       m.estimated_lines as complexity,
       call_frequency,
       (m.estimated_lines * call_frequency) as performance_risk_score,
       "Consider optimization or caching" as recommendation
ORDER BY performance_risk_score DESC
LIMIT 20
```

---

## 💡 Query Customization Tips

### Adding Business Context
Enhance queries with your specific business logic:

```cypher
// Add custom business criticality
MATCH (f:File)
WITH f,
  CASE 
    WHEN f.path CONTAINS "payment" OR f.path CONTAINS "billing" THEN "Business Critical"
    WHEN f.path CONTAINS "auth" OR f.path CONTAINS "security" THEN "Security Critical"  
    WHEN f.path CONTAINS "api" OR f.path CONTAINS "controller" THEN "Customer Facing"
    ELSE "Internal"
  END as business_impact
RETURN business_impact, count(f) as file_count
ORDER BY file_count DESC
```

### Parameterizing for Different Teams
Save queries with parameters for reuse:

```cypher
// Team-specific analysis template
MATCH (f:File)
WHERE f.path STARTS WITH $team_module_prefix
// ... rest of analysis
```

These examples show how graph analysis translates directly to business value. Each query answers a specific business question and provides actionable insights for technical leaders. 