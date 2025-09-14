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

// tag::top_central_methods[]
// Top methods by PageRank (requires centrality task write-back)
MATCH (m:Method)
WHERE m.pagerank_score IS NOT NULL
RETURN m.method_signature AS method,
       m.class_name       AS class,
       m.file             AS file,
       m.pagerank_score   AS score
ORDER BY score DESC, file, class, method
LIMIT 25
// end::top_central_methods[]

// tag::validate_louvain_writeback[]
// Validate Louvain write-back on similarity communities (if previously run)
MATCH (m:Method)
WHERE m.similarity_community IS NOT NULL
RETURN m.similarity_community AS community,
       count(*)               AS members
ORDER BY members DESC, community
LIMIT 10
// end::validate_louvain_writeback[]

// tag::high_blast_radius_methods[]
// High-impact targets for testing/refactoring: central methods called from many packages
// Value: prioritize changes where a defect has the widest blast radius across teams/modules.
MATCH (m:Method)
WHERE m.pagerank_score IS NOT NULL
OPTIONAL MATCH (caller:Method)-[:CALLS]->(m)
OPTIONAL MATCH (caller)<-[:CONTAINS_METHOD]-(callerClass:Class)<-[:CONTAINS]-(callerPkg:Package)
WITH m,
     count(DISTINCT caller) AS callers,
     count(DISTINCT callerPkg.name) AS caller_packages
RETURN m.method_signature AS method,
       m.pagerank_score   AS centrality,
       callers,
       caller_packages
ORDER BY centrality DESC, caller_packages DESC, callers DESC
LIMIT 25
// end::high_blast_radius_methods[]

// tag::community_modules_summary[]
// Candidate modules from similarity communities
// Value: reveal cohesive clusters that can map to modules or ownership boundaries.
MATCH (m:Method)
WHERE m.similarity_community IS NOT NULL
OPTIONAL MATCH (m)<-[:CONTAINS_METHOD]-(c:Class)<-[:CONTAINS]-(p:Package)
WITH m.similarity_community AS community,
     count(*)               AS members,
     count(DISTINCT c)      AS classes,
     count(DISTINCT p)      AS packages
RETURN community, members, classes, packages
ORDER BY members DESC, packages ASC
LIMIT 20
// end::community_modules_summary[]

// tag::fractured_classes_across_communities[]
// Classes whose methods span multiple communities (potential split/refactor candidates)
// Value: identify units where responsibilities are mixed across unrelated clusters.
MATCH (cls:Class)-[:CONTAINS_METHOD]->(m:Method)
WHERE m.similarity_community IS NOT NULL
WITH cls,
     count(DISTINCT m.similarity_community) AS distinct_communities,
     count(m) AS methods,
     apoc.coll.toSet(collect(DISTINCT m.similarity_community))[..5] AS sample
WHERE distinct_communities >= 2
RETURN cls.name AS class,
       cls.file AS file,
       methods,
       distinct_communities,
       sample AS communities
ORDER BY distinct_communities DESC, methods DESC
LIMIT 25
// end::fractured_classes_across_communities[]

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

// tag::api_exposes_internal_param_types[]
// Public API methods whose parameter types are in internal packages
// Params: $apiPrefix (e.g., 'com.app.api'), $internalPrefix (e.g., 'com.app.internal')
MATCH (api:Class)
WHERE api.package STARTS WITH $apiPrefix
MATCH (api)-[:CONTAINS_METHOD]->(m:Method {is_public:true})
MATCH (m)-[:HAS_PARAMETER]->(:Parameter)-[:OF_TYPE]->(t)
WHERE t.package STARTS WITH $internalPrefix
RETURN m.method_signature AS method,
       api.package        AS api_package,
       api.name           AS api_class,
       t.package          AS internal_package,
       t.name             AS internal_type
ORDER BY api_package, api_class, method
// end::api_exposes_internal_param_types[]

// tag::interface_implementations[]
// List classes that implement a given interface
// Params: $interface (e.g., 'Runnable')
MATCH (i:Interface {name: $interface})
MATCH (c:Class)-[:IMPLEMENTS]->(i)
RETURN i.name AS interface, c.name AS class, c.file AS file
ORDER BY interface, class
// end::interface_implementations[]


// (removed class_inheritance_chain: similar to extends tree; prefer the summarized chain)

// tag::interfaces_without_implementations[]
// Interfaces with no implementing classes (useful to spot dead/SDK-only contracts)
MATCH (i:Interface)
WHERE NOT ( (:Class)-[:IMPLEMENTS]->(i) )
RETURN i.name AS interface, i.file AS file
ORDER BY interface
// end::interfaces_without_implementations[]

// (removed type_hierarchy_implements: duplicate of interface_implementations)

// tag::type_hierarchy_extends_tree[]
// Show a class inheritance chain (ancestors) for a given class
// Param: $className e.g. 'ArrayList'
MATCH path=(c:Class {name: $className})-[:EXTENDS*]->(base:Class)
RETURN [n IN nodes(path) | n.name] AS inheritance_chain
ORDER BY size(nodes(path)) DESC
LIMIT 5
// end::type_hierarchy_extends_tree[]
