# Neo4j Code Graph

[![CI](https://github.com/alexwoolford/neo4j-code-graph/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/alexwoolford/neo4j-code-graph/actions/workflows/ci.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/alexwoolford/neo4j-code-graph/graph/badge.svg?token=JDCC5T84OG)](https://codecov.io/gh/alexwoolford/neo4j-code-graph)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Last Commit](https://img.shields.io/github/last-commit/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/commits/main)
[![Issues](https://img.shields.io/github/issues/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/issues)
[![Pull Requests](https://img.shields.io/github/issues-pr/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/pulls)

**Change-risk and vulnerability-reachability intelligence for Java
codebases.** Given a CVE in a dependency, tell me which of my methods can
actually reach it, how big the blast radius of fixing it is, and who owns
that code — in one query.

It ingests a Java repo into a Neo4j graph that joins four signals no
open-source tool combines in one place: **git history as a graph**
(Commit/Developer/FileVer + temporal coupling), **versioned Maven → CVE
linkage** (NVD/CPE + GHSA, version-range aware), a **method-level call
graph** including calls into external library APIs, and **GDS analytics**
(centrality, call-graph communities). For security engineers triaging
dependency CVEs and eng leads assessing change risk.

This **is not** a sound static analyser — the call graph is lexical, ranked
triage, not proof. See [Limitations](#limitations) before you ground a
security audit on it. If you need proof-grade dataflow, use CodeQL or Joern.

👉 Full documentation: https://alexwoolford.github.io/neo4j-code-graph/

## The pitch, on a real repo

Run against **OWASP WebGoat v8.1.0**:

```bash
code-graph-pipeline-prefect https://github.com/WebGoat/WebGoat.git --branch v8.1.0 --resolve-build-deps
code-graph-risk-report --risk-threshold 7.0 --max-hops 6
```

Dependency-level scanning flags 34 high-severity CVEs. Method-level
reachability turns that into a ranked, evidence-backed register — and clears
several as **not actionable** because your code never calls the vulnerable
dependency:

| CVE | CVSS | Dependency | Status | Evidence |
|-----|------|------------|--------|----------|
| CVE-2013-7285 | 9.8 | xstream:1.4.5 | **REACHABLE** (hop 0) | `VulnerableComponentsLesson#completed` calls `new XStream()` |
| CVE-2020-36518 | 7.5 | jackson-databind:2.10.1 | **REACHABLE** (hop 1) | `StoredXssComments#parseJson` → `ObjectMapper.readValue()` |
| CVE-2020-10683 | 9.8 | dom4j:2.1.1 | **NOT_IMPORTED** | no file imports dom4j — deprioritize |
| CVE-2017-18640 | 7.5 | snakeyaml:1.25 | **NOT_IMPORTED** | never called — deprioritize |

That's a **CVSS-9.8 CVE correctly cleared** as unreachable. Each REACHABLE
row also carries the shortest entry→frontier call path, the file's
CO_CHANGED blast radius, and the top committer. The single Cypher behind the
reachable rows:

```cypher
MATCH (cve:CVE {id: $cve_id})-[:AFFECTS]->(dep:ExternalDependency)
MATCH (imp:Import)-[:DEPENDS_ON]->(dep)
MATCH (frontier:Method)-[:CALLS_EXTERNAL]->(imp)
MATCH (entry:Method)-[:ANNOTATED]->(:Annotation)      // HTTP handlers, main, etc.
MATCH p = shortestPath((entry)-[:CALLS*0..6]->(frontier))
RETURN frontier.method_signature, length(p) AS hops, dep.artifact_id
ORDER BY hops
```

Read [`docs/reachability.md`](docs/reachability.md) for the confidence
tiers, ranking formula, soundness ceiling, and the full success-gate results.

## Quickstart

```bash
conda create -n neo4j-code-graph python=3.11 -y
conda activate neo4j-code-graph
pip install -e '.[dev]'
pip install -r config/requirements.txt
cp .env.example .env  # then edit with Neo4j credentials

# Full ingest, then the flagship report:
code-graph-pipeline-prefect <repo-url-or-local-path> --resolve-build-deps
code-graph-risk-report --risk-threshold 7.0

# Re-run later — only changed files are re-processed:
code-graph-pipeline-prefect <repo-url-or-local-path> --incremental
```

## MCP server

Expose the curated risk queries to coding agents (and humans) as typed,
read-only tools — `cve_reachability`, `blast_radius`, `hotspots`,
`ownership`, `risk_register`, `dependency_cves`, `unreachable_cves`,
`graph_summary`:

```bash
claude mcp add code-graph -- code-graph-mcp   # with NEO4J_* in the env
```

Details and a Cursor config snippet: the MCP page in the docs.

## What's in the graph

Per ingest, against a Java repo:

| Node label              | Source                                                                                         |
|-------------------------|------------------------------------------------------------------------------------------------|
| `Directory`, `Package`  | filesystem layout                                                                              |
| `File`, `FileVer`       | files at HEAD + per-commit revisions                                                           |
| `Class`, `Interface`    | tree-sitter type declarations. Records and enums also carry secondary `:Record` / `:Enum` labels |
| `Method`, `Parameter`   | with `arity`, modifiers (`is_public`/`is_protected`/`is_private`/`is_package_private`/`is_static`/`is_final`/`is_synchronized`/`is_default`), `cyclomatic_complexity`, and centrality scores after analytics |
| `Field`                 | with full visibility/storage modifiers (B1)                                                    |
| `Annotation`            | deduped by name (`@Override`, `@Autowired`, `@Entity`, …) (B1)                                 |
| `Exception`             | every type referenced in a `throws` clause (B1)                                                |
| `Doc`                   | Javadoc / leading comment block per type and method                                            |
| `Import`                | declared imports                                                                               |
| `ExternalDependency`    | versioned Maven coordinate (group_id + artifact_id + version)                                  |
| `CVE`                   | NVD vulnerability records that link to a versioned ExternalDependency                          |
| `Commit`, `Developer`   | from `git log`                                                                                 |

Relationships include: `CONTAINS`, `CONTAINS_METHOD`, `DECLARES`,
`DECLARES_FIELD`, `HAS_PARAMETER`, `OF_TYPE`, `IMPORTS`, `DEPENDS_ON`,
`EXTENDS`, `IMPLEMENTS`, `NESTED_IN`, `CREATES`, `CALLS`, `CALLS_EXTERNAL`,
`THROWS`, `ANNOTATED`, `HAS_DOC`, `AUTHORED`, `CHANGED`, `OF_FILE`,
`CO_CHANGED`, `AFFECTS`.

## Limitations

This project's analysis ceiling is honest and worth knowing up front. None of
these are bugs — they're shaped by the underlying tools.

### Call graph: receiver-class scoped, not type-scoped

The `CALLS` edge is built by tree-sitter parsing + name + receiver-class +
**arity** matching. It does not perform argument-type analysis. Specifically:

- **Cross-class fan-out**: avoided. A call to `obj.equals(...)` is not linked
  to every class with an `equals()` method, only to the resolved receiver
  class.
- **Within-class overload fan-out**: reduced (B2) but not eliminated. A call
  with N arguments is now narrowed to overloads of arity N, but if a class has
  multiple overloads of the same arity (e.g. `parse(String, String)` and
  `parse(String, URLWithScheme)`), they all receive a `CALLS` edge from the
  call site. Disambiguating these requires symbol-table-based type analysis,
  which tools like JavaParser+SymbolSolver, Joern, or CodeQL provide.
- **Super calls and constructor calls**: extracted with `call_type=super`
  / `call_type=constructor`. Super calls currently resolve to the same class
  (not the parent) — fixing this requires walking the EXTENDS chain at link
  time and is open work.
- **Reflection / DI / dynamic dispatch**: invisible. The graph reflects
  static, lexical structure only. Spring's `@Autowired` injections are
  visible (the annotation is captured), but the runtime wiring isn't.

For an empirical sanity check on a real repo: against `shapesecurity/salvation`
the post-B2 graph contains ~242 CALLS edges, of which arity-aware
disambiguation eliminated ~17% of pre-B2 spurious edges. The headline
overload case (`QueryingTest.parse` 3-overload fan-out) dropped from 72
edges → 29.

When using CALLS for security or refactor-blast-radius work, **always read
back the spurious-edge ratio** for your codebase via:

```cypher
MATCH (caller:Method)-[:CALLS]->(callee:Method)
WITH caller, callee.name AS name, callee.class_name AS cls,
     count(DISTINCT callee.method_signature) AS overloads_hit
WHERE overloads_hit > 1
RETURN cls, name, count(*) AS callers, sum(overloads_hit) AS edges
ORDER BY edges DESC LIMIT 20
```

### CVE matching

- Sources: NVD/CPE (primary, `nvd.nist.gov`) and — when in scope — GHSA. OSV
  is not yet integrated.
- A CVE only links to a dependency when **(a)** the dependency is versioned
  and **(b)** the dependency version falls inside an explicit version
  constraint on the CVE's CPE. Both are required (per AGENTS.md
  `cve_handling`).
- Maven version-range syntax (e.g. `[8.18,10.0)`) on a dependency is parsed
  and matched against CPE ranges (B4).
- `AFFECTS` edges carry a `confidence` and `match_type` for filtering.
- Heuristic / fuzzy matching is **off** by default to avoid false positives.

### Reachability is triage, not proof

`CALLS_EXTERNAL` (method → imported library API) is resolved from declared
types with confidence tiers: HIGH (static/constructor with an explicit
import), MEDIUM (instance call whose receiver's declared type resolves
in-file), LOW (single wildcard import). Chained/fluent calls, method
references, static imports, reflection, and DI wiring are **invisible**, so a
`NOT_IMPORTED`/`FRONTIER_UNREACHABLE` verdict is a strong deprioritization
signal, not a proof of safety. See [`docs/reachability.md`](docs/reachability.md).

### Test code is not separated from production code

Centrality treats test methods identically to production
methods. The `is_test_method` flag (B6) is the recommended filter:

```cypher
MATCH (m:Method) WHERE NOT coalesce(m.is_test_method, false)
RETURN m.class_name, m.name, m.in_degree
ORDER BY m.in_degree DESC LIMIT 10
```

### Java-only

Tree-sitter Java grammar only. C, Python, Go, Kotlin, etc. would each need
their own grammar + extractor. Out of scope for this project.

## Architecture

The pipeline is orchestrated by Prefect and runs as a deterministic DAG:

```
clone → extract → write graph (+ CALLS_EXTERNAL frontier)
                  → git history
                  → centrality + Louvain (on CALLS)
                  → CVE linking → risk report
```

State passes between stages via filesystem artifacts, not implicit DB state,
so any stage can be replayed individually. Each run records provenance
(`Repository`/`Ingest` nodes with the HEAD sha); a subsequent
`--incremental` run diffs against that high-water mark and patches only the
changed files, falling back to a full ingest when it cannot guarantee
parity (branch change, schema bump, non-ancestor HEAD, shallow clone).

Source layout:

- `src/analysis/` — parsers, centrality/temporal-coupling algorithms
- `src/data/` — schema management, graph writers
- `src/pipeline/` — Prefect tasks and flows
- `src/security/` — NVD client, GAV-CPE matcher, CVE-to-dep linking
- `src/utils/` — driver helpers, batching, cleanup

## Cypher cookbook

The hand-curated analyst cookbook lives in [`docs/COOKBOOK.md`](docs/COOKBOOK.md).
Each recipe is paired with a note on what it actually answers vs what an
analyst might assume it answers — important given the call-graph soundness
ceiling.

Risk-intelligence query walkthroughs (CVE exposure, blast radius, ownership)
are in [`examples/business_queries.md`](examples/business_queries.md); the
CI-validated query catalog is bound by [`examples/queries.yml`](examples/queries.yml).
Aim to use the schema-aware filters (`m.arity`, `m.is_test_method`,
`r.confidence` on AFFECTS) over name-based string matching wherever possible.

## Development

```bash
pre-commit run --all-files                          # ruff + black + mypy + codespell + interrogate
pytest -m "not live and not e2e and not security"   # fast unit path
pytest -m live                                      # live tests against a Neo4j you control
pip-audit -r config/requirements.txt                # CVE check on pinned deps
```

Live tests need either Docker (Testcontainers will start a Neo4j) or a
`NEO4J_*`-pointed test database that's safe to wipe — the `_reset_db_between_tests`
autouse fixture executes `MATCH (n) DETACH DELETE n` before every test.

## Upgrading an existing graph

Similarity/embeddings were removed from the pipeline; existing graphs can drop the artifacts:

```cypher
CALL apoc.periodic.iterate('MATCH ()-[r:SIMILAR]->() RETURN r','DELETE r',{batchSize:50000});
MATCH (m:Method) WHERE m.similarity_community IS NOT NULL REMOVE m.similarity_community;
MATCH (m:Method) WHERE m.embedding_unixcoder IS NOT NULL REMOVE m.embedding_unixcoder, m.embedding_type;
MATCH (f:File) WHERE f.embedding_unixcoder IS NOT NULL REMOVE f.embedding_unixcoder, f.embedding_type;
DROP INDEX method_similarity_community IF EXISTS;
DROP INDEX method_embeddings_embedding_unixcoder IF EXISTS;
```

## Related tools

We don't compete on agent-context (local-first indexing, many languages,
token savings) — CodeGraph, GitNexus, and friends own that space. Our
differentiation is the four-way join (git history × versioned-dependency
CVEs × method call graph × GDS) in one queryable graph; the nearest
neighbor is repowise, and CodeQL/Joern own sound static analysis. A cited
survey is in [`docs/modules/ROOT/pages/references.adoc`](docs/modules/ROOT/pages/references.adoc).

## License

MIT — see [LICENSE](LICENSE).
