# Risk-Intelligence Queries

How to answer the questions this project exists for: **given a CVE in a
dependency, what is my real exposure, what is the blast radius of fixing it,
and who owns that code?** Every query below runs against the actual graph
schema (see `docs/modules/ROOT/pages/graph-model-llm.adoc`); the canonical,
CI-validated versions live in `docs/modules/ROOT/examples/queries/`.

> **Soundness note:** the call graph is receiver-class + arity matched — no
> reflection, dependency injection, or dynamic dispatch. Treat results as
> ranked triage evidence, not proof. See README "Limitations".

## 1. Which files are exposed to a CVE?

The dependency chain is `File → Import → ExternalDependency ← CVE`. A file
that imports a vulnerable dependency's packages is *exposed* (necessary, not
sufficient, for exploitability).

```cypher
MATCH (cve:CVE)-[a:AFFECTS]->(dep:ExternalDependency)
      <-[:DEPENDS_ON]-(imp:Import)<-[:IMPORTS]-(f:File)
WHERE cve.cvss_score >= 7.0
RETURN cve.id            AS cve,
       cve.cvss_score    AS cvss,
       dep.group_id + ':' + dep.artifact_id + ':' + dep.version AS dependency,
       a.confidence      AS match_confidence,
       collect(DISTINCT f.path)[0..10] AS exposed_files
ORDER BY cvss DESC
```

`AFFECTS` edges carry `confidence` and `match_type` provenance — filter on
them when you need high-precision results.

## 2. Which CVEs have zero import exposure?

Triage-dismissal evidence: the dependency is flagged, but nothing in the
codebase imports its packages.

```cypher
MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)
WHERE NOT EXISTS { MATCH (dep)<-[:DEPENDS_ON]-(:Import) }
RETURN cve.id AS cve, cve.cvss_score AS cvss,
       dep.group_id + ':' + dep.artifact_id + ':' + dep.version AS dependency
ORDER BY cvss DESC
```

## 3. What is the blast radius of touching a file?

`CO_CHANGED` edges encode temporal coupling mined from git history
(`support` = co-change count, `confidence` = normalized strength). Files that
historically change together with your fix target are regression candidates.

```cypher
MATCH (f:File {path: $file_path})-[cc:CO_CHANGED]-(partner:File)
RETURN partner.path AS co_changed_file,
       cc.support   AS times_changed_together,
       round(cc.confidence * 100) / 100.0 AS confidence
ORDER BY cc.support DESC
LIMIT 20
```

## 4. Who owns the exposed code?

Ownership comes from git history: `Developer → Commit → FileVer → File`.

```cypher
MATCH (f:File {path: $file_path})<-[:OF_FILE]-(:FileVer)
      <-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
RETURN dev.name  AS developer,
       dev.email AS email,
       count(DISTINCT c) AS commits,
       max(c.date)       AS last_touched
ORDER BY commits DESC
LIMIT 5
```

A single dominant committer plus an old `last_touched` date means the fix
carries knowledge risk as well as regression risk.

## 5. End-to-end: CVE → exposed files → owners

The pitch in one query (file-level exposure joined with ownership):

```cypher
MATCH (cve:CVE)-[:AFFECTS]->(dep:ExternalDependency)
      <-[:DEPENDS_ON]-(:Import)<-[:IMPORTS]-(f:File)
WHERE cve.cvss_score >= 9.0
MATCH (f)<-[:OF_FILE]-(:FileVer)<-[:CHANGED]-(c:Commit)<-[:AUTHORED]-(dev:Developer)
WITH cve, dep, f, dev, count(DISTINCT c) AS commits
ORDER BY commits DESC
WITH cve, dep, f, collect(dev.name)[0] AS top_owner
OPTIONAL MATCH (f)-[cc:CO_CHANGED]-(:File)
RETURN cve.id AS cve,
       dep.artifact_id + ':' + dep.version AS dependency,
       f.path AS exposed_file,
       top_owner,
       count(cc) AS blast_radius
ORDER BY blast_radius DESC
LIMIT 25
```

## 6. Change-risk hotspots (no CVE required)

Frequently-changed files whose methods sit at the center of the call graph:

```cypher
MATCH (f:File)-[:DECLARES]->(m:Method)
WHERE f.change_count IS NOT NULL
  AND NOT coalesce(m.is_test_method, false)
WITH f, max(coalesce(m.pagerank_score, 0.0)) AS max_pagerank
RETURN f.path AS file, f.change_count AS changes,
       round(max_pagerank * 1000) / 1000.0 AS peak_method_pagerank
ORDER BY changes * max_pagerank DESC
LIMIT 20
```

---

**Method-level CVE reachability** — "which of my methods can *call into* the
vulnerable dependency, transitively" — is provided by the
`code-graph-risk-report` command and the `CALLS_EXTERNAL` frontier edges; see
`docs/reachability.md` once available. The file-level queries above are the
conservative baseline that works on any ingested graph.
