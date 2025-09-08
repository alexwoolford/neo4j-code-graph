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

// tag::package_risk_churn_fanout[]
// Churn-weighted package risk: packages that change often and depend on many packages
MATCH (p:Package)-[:CONTAINS]->(:Class)<-[:DEFINES]-(f:File)
MATCH (c:Commit)-[:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f)
WITH p, count(c) AS churn
MATCH (p)-[:CONTAINS]->(:Class)-[:CONTAINS_METHOD]->(m:Method)
MATCH (m)-[:CALLS]->(m2:Method)
MATCH (q:Package)-[:CONTAINS]->(:Class)-[:CONTAINS_METHOD]->(m2)
WHERE p <> q
WITH p, churn, count(DISTINCT q) AS fanoutPkgs
RETURN p.name AS package, churn, fanoutPkgs, churn*fanoutPkgs AS riskScore
ORDER BY riskScore DESC
LIMIT 15
// end::package_risk_churn_fanout[]

// tag::interface_implementations[]
// List classes that implement a given interface (optionally filter by package prefix)
// Params: $interface (e.g., 'I' or fully qualified short name), $packagePrefix (optional)
MATCH (i:Interface)
WHERE i.name = $interface OR ($packagePrefix IS NOT NULL AND i.file CONTAINS $packagePrefix AND i.name = $interface)
MATCH (c:Class)-[:IMPLEMENTS]->(i)
RETURN i.name AS interface, c.name AS class, c.file AS file
ORDER BY interface, class
// end::interface_implementations[]

// tag::class_inheritance_chain[]
// Show inheritance chain for a class (from the class up to its base)
// Param: $className
MATCH p=(c:Class {name:$className})-[:EXTENDS*0..]->(base:Class)
RETURN p
// end::class_inheritance_chain[]

// tag::interfaces_without_implementations[]
// Interfaces with no implementing classes (useful to spot dead/SDK-only contracts)
MATCH (i:Interface)
WHERE NOT ( (:Class)-[:IMPLEMENTS]->(i) )
RETURN i.name AS interface, i.file AS file
ORDER BY interface
// end::interfaces_without_implementations[]

// tag::type_hierarchy_implements[]
// Find all classes that implement a given interface
// Param: $ifaceName e.g. 'Runnable'
MATCH (i:Interface {name: $ifaceName})<-[:IMPLEMENTS]-(c:Class)
RETURN i.name AS interface, c.name AS class, c.file AS file
ORDER BY class, file
// end::type_hierarchy_implements[]

// tag::type_hierarchy_extends_tree[]
// Show a class inheritance chain (ancestors) for a given class
// Param: $className e.g. 'ArrayList'
MATCH path=(c:Class {name: $className})-[:EXTENDS*]->(base:Class)
RETURN [n IN nodes(path) | n.name] AS inheritance_chain
ORDER BY size(nodes(path)) DESC
LIMIT 5
// end::type_hierarchy_extends_tree[]
