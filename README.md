# Neo4j Code Graph

[![CI](https://github.com/alexwoolford/neo4j-code-graph/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/alexwoolford/neo4j-code-graph/actions/workflows/ci.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/alexwoolford/neo4j-code-graph/graph/badge.svg?token=JDCC5T84OG)](https://codecov.io/gh/alexwoolford/neo4j-code-graph)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Last Commit](https://img.shields.io/github/last-commit/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/commits/main)
[![Issues](https://img.shields.io/github/issues/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/issues)
[![Pull Requests](https://img.shields.io/github/issues-pr/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/pulls)

A structural- and ML-aided overview of a Java codebase, materialised as a Neo4j
knowledge graph. Combines tree-sitter Java parsing, Git history analysis,
UniXcoder method embeddings, GDS centrality + KNN similarity, and NVD/CPE +
GHSA CVE matching against versioned Maven dependencies. Useful for
collaboration analysis, hotspot discovery, dependency-vulnerability triage, and
exploratory architecture review via Cypher.

This **is not** a sound static analyser. See [Limitations](#limitations) below
before you ground a security audit on the call graph.

👉 Full documentation: https://alexwoolford.github.io/neo4j-code-graph/

## Quickstart

```bash
conda create -n neo4j-code-graph python=3.11 -y
conda activate neo4j-code-graph
pip install -e '.[dev]'
pip install -r config/requirements.txt
cp .env.example .env  # then edit with Neo4j credentials
code-graph-pipeline-prefect <repo-url-or-local-path> --resolve-build-deps
```

## What's in the graph

Per ingest, against a Java repo:

| Node label              | Source                                                                                         |
|-------------------------|------------------------------------------------------------------------------------------------|
| `Directory`, `Package`  | filesystem layout                                                                              |
| `File`, `FileVer`       | files at HEAD + per-commit revisions                                                           |
| `Class`, `Interface`    | tree-sitter type declarations. Records and enums also carry secondary `:Record` / `:Enum` labels |
| `Method`, `Parameter`   | with `arity`, modifiers (`is_public`/`is_protected`/`is_private`/`is_package_private`/`is_static`/`is_final`/`is_synchronized`/`is_default`), `cyclomatic_complexity`, `embedding_unixcoder` (768-dim), and centrality scores after analytics |
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
`EXTENDS`, `IMPLEMENTS`, `NESTED_IN`, `CREATES`, `CALLS`, `THROWS`,
`ANNOTATED`, `HAS_DOC`, `AUTHORED`, `CHANGED`, `OF_FILE`, `CO_CHANGED`,
`SIMILAR`, `AFFECTS`.

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

### Embeddings and similarity

- Method bodies are embedded with `microsoft/unixcoder-base` (768-dim, CLS
  pooled). Methods over ~512 tokens are silently truncated; trivial methods
  (`return x;`) embed nearly identically across unrelated classes. KNN
  `SIMILAR` results should be read as "syntactically/structurally similar
  code", not "semantically equivalent".
- KNN parameters: `topK=5`, `similarityCutoff=0.8`. These are defaults;
  validate against your codebase before drawing conclusions.
- GDS produces single-direction `SIMILAR` edges in 2.x; older 1.x produced
  bidirectional. The pair count is the same; the edge count differs by ~2x.

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

### Test code is not separated from production code

Centrality and similarity treat test methods identically to production
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
clone → extract → embed (file + method) → write graph
                                          → git history
                                          → centrality + KNN + Louvain
                                          → CVE linking
```

State passes between stages via filesystem artifacts, not implicit DB state,
so any stage can be replayed individually.

Source layout:

- `src/analysis/` — parsers, embedders, similarity/centrality/temporal-coupling algorithms
- `src/data/` — schema management, graph writers
- `src/pipeline/` — Prefect tasks and flows
- `src/security/` — NVD client, GAV-CPE matcher, CVE-to-dep linking
- `src/utils/` — driver helpers, batching, cleanup

## Cypher cookbook

Sample queries are in [`examples/queries.yml`](examples/queries.yml) and
[`cypher_templates_for_bloom.cypher`](cypher_templates_for_bloom.cypher).
Aim to use the schema-aware filters (`m.arity`, `m.is_test_method`,
`r.confidence` on AFFECTS) over name-based string matching wherever possible.

## Development

```bash
pre-commit run --all-files                          # ruff + black + mypy + codespell + interrogate
pytest -m "not live and not e2e and not security"   # fast unit path (~309 tests)
pytest -m live                                      # live tests against a Neo4j you control
pip-audit -r config/requirements.txt                # CVE check on pinned deps
```

Live tests need either Docker (Testcontainers will start a Neo4j) or a
`NEO4J_*`-pointed test database that's safe to wipe — the `_reset_db_between_tests`
autouse fixture executes `MATCH (n) DETACH DELETE n` before every test.

## License

MIT — see [LICENSE](LICENSE).
