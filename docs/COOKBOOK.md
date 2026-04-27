# Analyst Cookbook

A short collection of Cypher recipes against the Neo4j Code Graph schema.
Read [the README's Limitations section](../README.md#limitations) before you
build a story on top of any number you see here.

Every query below is paired with a brief note on **what it actually answers**
versus **what an analyst might think it answers**. The two often differ in
this graph because of the soundness ceiling on `CALLS`.

---

## Hub methods, but only production code

Centrality numbers (`in_degree`, `pagerank_score`) are computed on the
post-B2 call graph, which has ~17% spurious edges remaining (within-class
overload fan-out). Combine the centrality numbers with the
`is_test_method` filter to keep test infrastructure out of the ranking.

```cypher
MATCH (m:Method)
WHERE NOT coalesce(m.is_test_method, false)
RETURN m.class_name AS class, m.name, m.arity, m.in_degree
ORDER BY m.in_degree DESC, m.class_name, m.name
LIMIT 20;
```

Caveat: `in_degree` overcounts when a class has multiple overloads of the
same arity. Run the noise check below if a number looks too large.

## CALLS noise floor (run this on every new ingest)

```cypher
MATCH (caller:Method)-[:CALLS]->(callee:Method)
WITH caller, callee.name AS name, callee.class_name AS cls,
     count(DISTINCT callee.method_signature) AS overloads_hit
WHERE overloads_hit > 1
RETURN cls, name, count(*) AS callers, sum(overloads_hit) AS edges
ORDER BY edges DESC
LIMIT 10;
```

Each row is a name + class where N callers each linked to M overloads
because arity alone wasn't enough to disambiguate. The `edges` total is
roughly the number of spurious CALLS in that group.

## "Who implements interface X?"

`IMPLEMENTS` is captured at write time when a Java `class C implements I`
clause is parsed. Use this to find concrete classes for an interface:

```cypher
MATCH (cls:Class)-[:IMPLEMENTS]->(iface:Interface {name: $interface_name})
RETURN cls.package, cls.name, cls.file
ORDER BY cls.package, cls.name;
```

## Framework-aware: every Spring controller

```cypher
MATCH (cls:Class)-[:ANNOTATED]->(:Annotation {name: 'RestController'})
RETURN cls.package, cls.name
ORDER BY cls.package, cls.name;
```

Generalise: `:Annotation` nodes are deduped by name across the whole
codebase, so any annotation (`@Entity`, `@Test`, custom `@MyAnnotation`)
queries the same way.

## Field-level coupling

Fields previously didn't exist in the graph. Now you can ask:

```cypher
// Fields with @Autowired (or any DI annotation)
MATCH (cls:Class)-[:DECLARES_FIELD]->(f:Field)-[:ANNOTATED]->(a:Annotation {name: 'Autowired'})
RETURN cls.name AS class, f.name AS field, f.type AS type
ORDER BY class, field;

// Public mutable fields (typically a code-smell flag)
MATCH (cls:Class)-[:DECLARES_FIELD]->(f:Field)
WHERE f.is_public AND NOT f.is_final
RETURN cls.package, cls.name, f.name, f.type
ORDER BY cls.package, cls.name;
```

## Inner-class linkage

```cypher
// All inner types and their parent
MATCH (child)-[:NESTED_IN]->(parent)
RETURN parent.name AS outer, child.name AS nested,
       labels(child) AS kind
ORDER BY parent.name, child.name;
```

## Throws / exception propagation

```cypher
// Methods that can throw a specific checked exception
MATCH (m:Method)-[:THROWS]->(:Exception {name: 'IOException'})
RETURN m.class_name, m.name, m.method_signature
ORDER BY m.class_name, m.name;
```

## Temporal coupling — files that change together

`CO_CHANGED` edges are pruned at ingest by `min_support` (default 5) and
`confidence_threshold` (default 0.6), but those values are configurable.
The `support` is the number of commits where both files were changed; the
`confidence` is symmetric and capped at 1.0.

```cypher
// Top temporal-coupling pairs by support
MATCH (a:File)-[r:CO_CHANGED]->(b:File)
WHERE a.path < b.path  // dedupe direction
RETURN a.path, b.path, r.support, r.confidence
ORDER BY r.support DESC, r.confidence DESC
LIMIT 20;
```

## Vulnerability provenance

Every `AFFECTS` edge carries enough metadata to explain why a CVE was
linked to a dependency:

```cypher
// Why was this CVE linked? Show the match shape and confidence.
MATCH (cve:CVE)-[r:AFFECTS]->(ed:ExternalDependency)
WHERE cve.id = $cve_id
RETURN ed.group_id, ed.artifact_id, ed.version,
       r.confidence, r.match_type, r.created_at, cve.severity, cve.cvss_score
ORDER BY r.confidence DESC;
```

```cypher
// All AFFECTS edges below a confidence threshold (likely fuzzy matches)
MATCH (cve:CVE)-[r:AFFECTS]->(ed:ExternalDependency)
WHERE r.confidence < 0.9
RETURN cve.id, ed.group_id, ed.artifact_id, ed.version,
       r.confidence, r.match_type
ORDER BY r.confidence ASC;
```

## Developer activity

`Developer` nodes are deduped by email. The same human who commits with
two emails will appear as two `Developer` nodes; that's a separate
entity-resolution problem we deliberately don't solve here.

```cypher
// Top contributors by commit count
MATCH (d:Developer)-[:AUTHORED]->(c:Commit)
RETURN d.name, d.email, count(c) AS commits
ORDER BY commits DESC
LIMIT 10;
```

```cypher
// Files touched by exactly one developer (single-owner risk)
MATCH (d:Developer)-[:AUTHORED]->(c:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(f:File)
WITH f, count(DISTINCT d) AS authors
WHERE authors = 1
RETURN f.path
ORDER BY f.path;
```

## Method-level similarity (KNN over embeddings)

```cypher
// Methods structurally similar to a target -- 0.8 cutoff is the default
// at write time, so any edge here is already above that.
MATCH (target:Method {method_signature: $sig})-[r:SIMILAR]-(other:Method)
RETURN other.class_name, other.name, r.score
ORDER BY r.score DESC
LIMIT 10;
```

Caveat: trivial methods (e.g. plain getters) embed near-identically across
unrelated classes. Filter on `m.estimated_lines >= 5` if you only want
methods with substantive bodies.

---

## What's NOT in this cookbook

- Production-grade taint tracking, def-use chains, or dataflow analysis.
  Tree-sitter + this graph cannot answer "is user input reaching this sink?";
  use CodeQL / Joern / Semgrep for that.
- Reflection or DI runtime resolution. The graph captures `@Autowired`
  annotations; it does not resolve them to concrete bean types.
- Cross-language analysis. Java only.
