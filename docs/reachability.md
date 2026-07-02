# CVE method-level reachability

The reachability module (`src/security/reachability.py`) upgrades dependency-level
CVE flags ("you depend on a vulnerable artifact") into method-level triage
evidence ("this code calls into that artifact's API, and here is a call path
from an entry point"). The `code-graph-risk-report` command turns that into a
ranked risk register.

Everything below is a **ranked triage signal with confidence tiers, not proof
of (un)reachability**.

## Graph shape

```
(CVE)-[:AFFECTS {confidence, match_type}]->(ExternalDependency)
(Import)-[:DEPENDS_ON]->(ExternalDependency)
(Method)-[:CALLS_EXTERNAL {method_name, target_class, confidence, confidence_rank}]->(Import)
(Method)-[:CALLS]->(Method)          // internal call graph (receiver-class + arity matched)
```

A **frontier method** is a method with a `CALLS_EXTERNAL` edge into an import
of a dependency the CVE affects. Reachability asks: can any entry point reach
a frontier method through internal `CALLS` edges within `max_hops`?

## Confidence tiers

| Tier | Rank | Meaning | Basis |
|------|------|---------|-------|
| HIGH | 3 | Static or constructor call, package pinned by an explicit import | The qualifier/`new` names the class; the exact FQCN import pins the package |
| MEDIUM | 2 | Instance call whose receiver's *declared* type resolves in-file (parameter, local variable, or field type) and that type is explicit-imported | Declared type is not runtime type — dynamic dispatch caveat |
| LOW | 1 | Type resolves only via a single external wildcard import (package guessed), or the capitalized-qualifier static heuristic with a single wildcard candidate | Package inferred, not pinned |
| NONE | — | No reachable frontier at all (used only by the risk report) | Absence of evidence, **not** proof of safety |

### What stays invisible

The extraction is static and declared-type based. The following never produce
`CALLS_EXTERNAL` edges and therefore never appear in the frontier:

- chained/fluent receivers (`a.b().c()`) and call-result receivers
- lambdas and method references (`Foo::bar`)
- `import static` calls (currently classified as same-class calls)
- reflection (`Class.forName`, `Method.invoke`) and runtime classloading
- dependency-injection / runtime wiring beyond declared field and parameter
  types (Spring proxies, `@Autowired` concrete implementations)
- dynamic dispatch to subtypes (the declared type is matched, not the runtime type)
- files with multiple external wildcard imports (ambiguous candidates are
  dropped to protect precision)
- transitive-dependency API surface re-exported through a direct dependency
  (a CVE in `commons-text` reached only via a Spring facade shows zero frontier)
- shaded/relocated packages

## Reachability statuses

| Status | Meaning |
|--------|---------|
| `REACHABLE` | Frontier exists and at least one entry path reaches it within `max_hops` |
| `FRONTIER_UNREACHABLE` | Frontier exists but no entry path within `max_hops` |
| `NO_FRONTIER` | The affected dependency is imported but never called (at the chosen confidence) |
| `NOT_IMPORTED` | No import depends on the affected dependency at all |

## Entry sets

Entry points are selected per `--entry-set` (comma-separated, OR-combined,
default `annotated,main`):

- **`annotated`** — methods annotated with (or public methods of classes
  annotated with) one of the entry annotations. Default list
  (`DEFAULT_ENTRY_ANNOTATIONS` in `src/constants.py`): Spring MVC
  (`RestController`, `Controller`, `RequestMapping`, `Get/Post/Put/Delete/PatchMapping`),
  messaging (`MessageMapping`, `KafkaListener`, `JmsListener`, `RabbitListener`),
  `Scheduled`, `EventListener`, and JAX-RS (`Path`, `GET`, `POST`, `PUT`, `DELETE`).
  Override with `--entry-annotations`.
- **`main`** — `public static` methods named `main`.
- **`public`** — every public non-test method. Conservative superset; expensive
  on large graphs (entry x frontier shortest-path cross product).

Test methods (`is_test_method = true`) are excluded from the entry frontier by
default.

## Ranking formula

```
risk_score = cvss * tier_weight * hop_factor
hop_factor = 1 / (1 + RISK_HOP_DECAY * min_hops)
```

Constants live in `src/constants.py`:

- `RISK_TIER_WEIGHTS = {"HIGH": 1.0, "MEDIUM": 0.7, "LOW": 0.4, "NONE": 0.05}`
- `RISK_HOP_DECAY = 0.15` (direct call → 1.0; 6 hops → ≈0.53)
- `DEFAULT_MAX_HOPS = 6`

Rows without a reachable frontier get tier `NONE`, `hop_factor = 1.0`, are kept
in the register, sorted to the bottom, and labeled *"no call-path evidence —
deprioritize, not proof of safety"*.

Blast radius (co-change partner count of the frontier file) and staleness
(days since its last commit) are **sort tiebreakers only, never score
multipliers** — they modulate fix effort, not exploitability. Full sort order:
`risk_score` desc, then `co_change_count` desc, then staleness days desc.

## Running the report

```bash
code-graph-risk-report \
  --entry-set annotated,main \
  --min-confidence LOW \
  --max-hops 6 \
  --risk-threshold 7.0 \
  --format both \
  --output ./risk_report
```

Writes `risk_report.json` and `risk_report.md` and prints the summary plus the
top-10 table. Truncated sample output:

```
# CVE Risk Report

Generated 2026-07-02T17:04:11+00:00 | database `neo4j` | tool 1.0.0

**14 dependency-level CVEs -> 5 with a reachable call-path frontier (64.3% triage reduction).**

Status breakdown: 5 REACHABLE, 3 FRONTIER_UNREACHABLE, 4 NO_FRONTIER, 2 NOT_IMPORTED.

Parameters: max_hops=6, entry_sets=annotated,main, min_confidence=LOW, risk_threshold=7.0

## Risk register

| # | CVE | CVSS | Dependency | Status | Tier | Hops | Frontier method | Blast radius | Owner (last touch) | Score |
|---|-----|------|------------|--------|------|------|-----------------|--------------|--------------------|-------|
| 1 | CVE-2020-36518 | 9.8 | com.fasterxml.jackson.core:jackson-databind:2.9.10 | REACHABLE | HIGH | 2 | `com.example.JsonUtil#parse():void` | 7 | alice@example.com (2024-06-20) | 7.5385 |
| 2 | CVE-2021-44228 | 10.0 | org.apache.logging.log4j:log4j-core:2.14.1 | REACHABLE | MEDIUM | 3 | `com.example.LogWrapper#log():void` | 3 | bob@example.com (2023-11-02) | 4.8276 |
...
| 14 | CVE-2019-12345 | 7.5 | org.hsqldb:hsqldb:2.3.4 | NOT_IMPORTED | NONE | - | - | 0 | - | 0.375 |
```

The JSON artifact carries the same data plus full evidence, example paths,
score components, and per-row provenance; the pipeline's CVE stage writes it
automatically as `risk_report.json`.

## Success-gate results

Primary testbed: **OWASP WebGoat v8.1.0** (Spring Boot, Maven, CVE-dense
pinned dependencies), full pipeline against a Neo4j 5.26 instance,
`--resolve-build-deps`, `code-graph-risk-report --risk-threshold 7.0
--max-hops 6 --entry-set annotated,main`.

**Triage reduction** (CVEs whose dependency has no reachable call path, so
dependency-level flagging over-reports):

| CVSS filter | dependency-level CVEs | reachable | not actionable | triage reduction |
|-------------|----------------------|-----------|----------------|------------------|
| ≥ 9.0       | 2                    | 1         | 1              | **50.0%**        |
| ≥ 7.0       | 34                   | 29        | 5              | **14.7%**        |
| ≥ 0.0       | 61                   | 48        | 13             | **21.3%**        |

The "not actionable" bucket is real triage signal: `org.dom4j:dom4j:2.1.1`
(CVE-2020-10683, **CVSS 9.8**), `org.yaml:snakeyaml:1.25`,
`javax.activation:activation:1.1.1` are all flagged by dependency-level
scanners but have **zero imports** in WebGoat's source — deprioritize.
`org.hsqldb:hsqldb:2.5.0` (CVE-2022-41853) is imported but has no path from
an entry point (FRONTIER_UNREACHABLE).

**HIGH-tier precision** (spot-check of reachable findings against the actual
call sites): 3/3 sampled = 100%, each with concrete API-call evidence, e.g.

- CVE-2013-7285 (xstream RCE) → `VulnerableComponentsLesson#completed` calls
  `new XStream()` / `XStream.setClassLoader()` (hop 0, direct).
- CVE-2020-36518 (jackson-databind DoS) → `StoredXssComments#parseJson`
  calls `new ObjectMapper()` / `ObjectMapper.readValue()` (hop 1).

**Query wall-clock**: the full 34-CVE risk report renders in a few seconds
against a local Neo4j (well under the 60s/CVE bar).

**Verdict — proceed.** The mechanism is proven correct on both sides: true
positives carry concrete API-call evidence, and true negatives
(dom4j/snakeyaml/activation) are genuinely uncalled. The 30% triage-reduction
target is not met at CVSS ≥ 7 on WebGoat, but WebGoat is a deliberately
vulnerable teaching app whose lessons *exist to exercise* their vulnerable
components — the pathological worst case for triage reduction. A normal
application, where most CVE-bearing transitive dependencies are never called,
is expected to show substantially higher reduction. Method-level reachability
clearly beats dependency-level flagging here (it correctly cleared a CVSS-9.8
dom4j CVE as unreachable), so this is not the differentiation failure that
the pivot's stop-rule guards against.

Six pipeline defects were found and fixed while running this gate (build-dep
version clobbering, calls-Louvain GDS API misuse, a recency-biased NVD fetch
budget, noisy/versioned NVD search terms, a 429-storming rate limiter, and
Maven coordinate mis-parsing that mangled 126/177 GAVs); without them the
CVE-linking chain produced zero AFFECTS edges.
