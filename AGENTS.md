# AGENTS Guidance

This document captures hard requirements and conventions for agents contributing to this repository.

**Global Rule: All critical preconditions must fail fast (schema, embeddings, dependency versions). Never allow silent fallbacks.**

## Neo4j usage
- Always create and close drivers/sessions using context managers: `with driver:` and `with driver.session(...) as session:`.
- Do not migrate or mutate existing DB data implicitly. End-to-end flows must work without manual repair steps.
- Ensure required constraints/indexes exist before writes (fail fast if missing).

## Embedding property
- Use one canonical method/file embedding property across the project via `src/constants.py`:
  - `EMBEDDING_PROPERTY = f"embedding_{EMBEDDING_TYPE}"`
- Writers and readers MUST use the constant; do not hardcode the property name.
- Similarity must fail early with a clear error if no methods have `EMBEDDING_PROPERTY` set.

## CVE handling
- Version-aware only: link CVEs to dependencies strictly when CVE version constraints match the dependency version.
- Only consider `ExternalDependency` nodes where `version IS NOT NULL` for `AFFECTS` queries and relationships.
- Ignore CVEs without version constraints for linkage (both precise and fuzzy paths).
- Cache CVE queries persistently; resume partial searches; respect TTL for complete caches to avoid redundant work.
- Strict policy: NEVER link a CVE to a dependency that lacks a version. Even if names/path look right, skip until a concrete dependency version is available.
- CVE range evaluation must be based on explicit semantic/comparable versions; fall back to "no link" if version parsing fails.

## NVD searches (coverage and rate limiting)
- 100% coverage: when running the end-to-end pipeline, the NVD search MUST cover all relevant external dependencies detected in the graph (not a subset).
- Use batching to remain under NVD rate limits:
  - With API key: 50 requests/30s; without: 5 requests/30s.
  - Group search terms to minimize requests, but iterate all groups until 100% of dependencies have been processed.
- Backoff on 429 and honor `Retry-After` headers; do not exceed limits.
- Log coverage explicitly: `covered X/Y dependencies` at the end of the search.

## Temporal coupling (large repos)
- Use APOC `apoc.periodic.iterate` to build `CO_CHANGED` support in batches; skip pathological commits (configurable threshold) and support optional time windows.
- Compute confidence and prune below threshold in a second step.

## Testing
- Live tests must use driver/session context managers and avoid deprecation warnings.
- Prefer live integration tests for critical paths and keep unit tests for fast shape/logic validation.

# Planning and Self-Reflection (Zero-to-One tasks)

When designing non-trivial or zero-to-one features, leave explicit room for planning and self-reflection before building. Use the following internal scaffold to force high-quality thinking. Do not surface the rubric to users; it is for agent use only.

```
<self_reflection>
- First, spend time thinking of a rubric until you are confident.
- Then, think deeply about every aspect of what makes for a world-class one-shot web app (or feature) in this context. Use that knowledge to create a rubric that has 5–7 categories. This rubric is critical to get right, but do not show this to the user. This is for your purposes only.
- Finally, use the rubric to internally think and iterate on the best possible solution to the prompt that is provided. Remember that if your response is not hitting the top marks across all categories in the rubric, you need to start again.
</self_reflection>
```

Operational guidance:
- Apply the self_reflection step before proposing an implementation plan for complex user requests.
- Keep the rubric internal; communicate only the resulting plan/edits that meet the rubric’s bar.
- If trade-offs arise (time, reliability, scope), state them explicitly and justify decisions against the rubric.

# AGENTS Instructions

## 🚨 CRITICAL: ZERO TOLERANCE FOR CI FAILURES

**🔥 SYSTEMIC FIX: Automatic pre-commit validation is now ENFORCED**

### ⚡ Commit Safely (Recommended)

```bash
# Always validate before committing
pre-commit run --all-files

# Commit only when all checks pass
git add -A && git commit -m "your message"
```

### 🛡️ AUTOMATIC GIT HOOK (Already Installed)

Git is now configured to automatically run pre-commit checks before ANY commit:
- ✅ Pre-commit hook automatically runs on `git commit`
- ✅ Blocks commits that would fail CI
- ✅ Shows exactly what needs to be fixed
- ✅ No more CI surprises!

### 💥 MANUAL METHOD (Fallback)

**⚠️ MANDATORY: Run pre-commit hooks before EVERY commit - this is what CI runs!**

```bash
# 🔥 THE SINGLE COMMAND THAT PREVENTS ALL CI FAILURES:
pre-commit run --all-files

# This runs the EXACT same checks as CI:
# ✅ black (code formatting)
# ✅ isort (import sorting)
# ✅ flake8 (style violations)
# ✅ mypy (type checking)
# ✅ trim whitespace, fix end of files, etc.

# 🚨 CRITICAL: If ANY check fails, DO NOT commit until fixed!
```

**🔥 Golden Rule: `pre-commit run --all-files` must show "Passed" for all checks!**

### Quick Fix Commands:
```bash
# Fix most issues automatically:
make format  # Runs black + isort to fix formatting/imports

# Then re-run to verify:
pre-commit run --all-files

# Only commit when ALL checks pass!
```

## Development Setup

1. **Environment Setup**:
```bash
# Activate the project conda environment
conda activate neo4j-code-graph

# Install dependencies
pip install -e .[dev]
pip install -r config/requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env with your Neo4j credentials
```

2. **Code Quality Tools**:
```bash
# CRITICAL: Fix import sorting (prevents CI failures)
isort src/ tests/ scripts/

# Format code (required before commits)
black src/ tests/ scripts/

# Check import sorting (CI requirement)
isort --check-only --diff src/ tests/ scripts/

# Check code formatting
black --check --diff src/ tests/ scripts/

# Check style
flake8 src/ tests/ --max-line-length=100

# Type checking
mypy src/ --ignore-missing-imports

# Run all quality checks at once
make format-check  # Check formatting without changes
make lint         # Run flake8 and mypy

# Auto-fix formatting issues
make format       # Runs both black and isort

# Run tests
python -m pytest tests/ -v
```

3. **⚠️ IMPORT SORTING CRITICAL**:
```bash
# ALWAYS run before committing to prevent CI failures:
isort src/ tests/ scripts/

# The project uses isort with "black" profile for consistent import ordering:
# - Standard library imports first (alphabetically sorted)
# - Third-party imports second (alphabetically sorted)
# - Local imports last (alphabetically sorted)
# - Blank lines between groups
# - Imports within 'from' statements alphabetically sorted

# Example of correct import order:
import argparse
import logging
import sys

import pandas as pd
import torch

from utils.common import create_neo4j_driver, setup_logging
```

## Architecture Overview

- **`code_to_graph.py`**: Loads Java code structure with embeddings (GPU accelerated)
- **`git_history_to_graph.py`**: Imports Git commit history and developer data (15-30x faster)
- **`create_method_similarity.py`**: Creates method similarity relationships using KNN
- **`cleanup_graph.py`**: Flexible cleanup tool (selective or complete database reset)
- **`temporal_analysis.py`**: Temporal analyses (coupling, hotspots)
- **`common.py`**: Shared utilities to reduce code duplication
- **`utils.py`**: Core utility functions (port handling, config)


## Provider-Agnostic Policy (Git Hosting)

- Do not add GitHub-, GitLab-, Bitbucket-, or other vendor-specific integrations to the pipeline logic.
- The pipeline must work with any Git repository URL; no hard dependencies on vendor APIs.
- External vulnerability data must come from provider-neutral sources (NVD) only.
- Vendor-specific data may be used for validation in ad-hoc scripts, but must not be required for pipeline execution.


## Neo4j Aura Compatibility Policy

- **Scope**: All database interactions must be compatible with Neo4j Aura.
- **Allowed**: Standard Cypher, APOC core procedures, and standard Neo4j GDS library algorithms.
- **Disallowed**:
  - APOC extended procedures or functions (e.g., those requiring filesystem or external network access)
  - Custom plugins, user-defined procedures, unmanaged extensions
  - Any functionality not supported on Aura
- **Design rule**: If a proposed approach relies on any Aura-incompatible feature, it will not be adopted. Provide an Aura-compatible alternative (pure Cypher/APOC core/GDS) instead.
- **Review checklist**:
  - No usage of APOC extended namespaces
  - No file or network access within the database context
  - No custom server plugins required
  - GDS calls are from supported, standard procedures

## Testing Strategy
## Schema Enforcement Policy
## Connection Configuration Policy
### Test scope alignment (MANDATORY)

- Do not write tests for behaviors or features the pipeline does not implement.
- Tests must reflect the current DAG and code paths. If a behavior is optional or future-facing (e.g., file-level embeddings), do not add tests for it unless it is explicitly part of the active pipeline.
- When in doubt, inspect `src/pipeline/prefect_flow.py` and the modules it calls; derive tests from those tasks only.
- Prefer:
  - Unit tests for small, deterministic helpers.
  - Live tests for behaviors that depend on Neo4j/GDS (use the existing Testcontainers/CI live job).
- Avoid brittle tests that assert internal implementation details; assert externally visible effects (created nodes/relationships, properties, query results).

### Testing Philosophy and Use of Test Doubles (MANDATORY)

- Default stance: test real code paths. Do not write “placeholder” tests that merely assert that mocks were called.
- Avoid MagicMock/monkeypatch unless absolutely necessary. Acceptable cases:
  - Isolating hard external boundaries (e.g., network/NVD API rate limits, filesystem hazards).
  - Bypassing optional/unsupported runtime dependencies in specific CI jobs (e.g., Arrow/tqdm.auto path in GDS) while the same behavior is covered in live/integration tests elsewhere.
  - Creating small value-preserving fakes (minimal objects that act like real ones) instead of loose mocks for complex protocols.
- Prefer live or realistic integration tests for critical paths (Neo4j schema, writers, GDS projections/algorithms). Use Testcontainers/Neo4j for these.
- When a test double is unavoidable:
  - Scope it narrowly, assert real outputs or side effects (Cypher issued, properties set), and avoid asserting on call counts alone.
  - Document the rationale in the test (why a real dependency isn’t feasible) and ensure a live/integration counterpart exists covering the same behavior.


- Single source of truth for Neo4j connection is `.env` loaded via `src/utils/neo4j_utils.get_neo4j_config()`.
- All stages (CLI, Prefect tasks, GDS helpers) must use either:
  - Explicit CLI args passed through the flow, or
  - `get_neo4j_config()`; never hardcode fallbacks like `bolt://localhost:7687`.
- If args and `.env` disagree, args win. Never silently swap to localhost.
- Action item: avoid any default `localhost` strings in code; use `ensure_port()` on provided URI.
- Database name must never be hardcoded (e.g., `"neo4j"`). Always resolve via CLI args or `.env` (`NEO4J_DATABASE`) using `get_neo4j_config()`. If unset, abort or pass through rather than defaulting silently.

- Never assume a default password. The project must not fall back to `"neo4j"` or any other value for `NEO4J_PASSWORD`. All connection settings (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`) are required and must come from CLI args or environment. Code that connects to Neo4j MUST error out if any are missing instead of using implicit defaults.


- All writes MUST run only after core schema constraints exist.
- The pipeline performs a fail-fast check at the start of each write stage. If constraints are missing, it will attempt to create the schema; if still missing, it aborts the run.
- Manual schema setup (optional):
  - Run: `python -m src.data.schema_management --verify-only` to inspect
  - Run: `python -m src.data.schema_management` to create constraints and indexes


Tests use mocked database connections for execution without requiring a running Neo4j instance. For integration testing:

1. Setup test Neo4j instance
2. Create `.env` file with test database credentials
3. Run individual scripts against test data
4. Verify results using Neo4j Browser

## Performance Considerations

### **GPU Optimizations**
- **Apple Silicon**: MPS batch size 256 (4x faster) with high-performance mode
- **CUDA**: Automatic detection with mixed-precision support
- **Memory management**: Efficient cache clearing prevents OOM errors

### **Transformer Workloads (Policy)**
- Always prefer GPU (CUDA) or MPS if available; fall back to CPU.
- Always process inputs in batches; avoid per-item forward passes:
  - UniXcoder code embeddings: large batches (128–256) depending on device.
  - CodeT5 summarization: smaller batches (default 16) due to decoder generation cost.
- Centralize batch sizes and generation settings in `src/constants.py`.
- Use CLS pooling for encoder-only embeddings; keep vectors at 768-D.

### **Progress Visibility for Long-Running Batches**
- Use `tqdm` progress bars for transformer batch loops and other long operations.
- Default pattern:
  - Wrap `range(0, N, batch_size)` with `tqdm(..., desc="<action>", unit="batch")`.
  - Fall back to periodic `print` if `tqdm` unavailable.
- This is mandatory for summarization, embedding, and similar steps to provide user feedback.

### **Git History Performance**
- **15-30x faster**: 3-step CREATE vs 5-step MERGE operations
- **Large batches**: 25K records per batch with progress reporting
- **Memory efficient**: Handles 300K+ nodes without memory issues

### **General Performance**
- **Git extraction**: ~9,600 commits/sec using git log commands
- **Bulk loading**: Uses UNWIND queries for efficient Neo4j writes
- **Session management**: Scripts use fresh sessions and retry logic for resilience
- **Smart fallbacks**: Automatic branch detection (main/master/HEAD)

## Dependency Management

- **GraphDataScience version**: Ensure GDS version matches `config/requirements.txt`
- **PyArrow compatibility**: Must be `>=17.0,<21.0` for GDS compatibility
- **CUDA/MPS support**: PyTorch automatically detects GPU acceleration

## Common Issues

1. **Session timeouts**: Use `--skip-file-changes` for testing
2. **Memory issues**: Large repositories may hit cloud Neo4j memory limits
   - Use `cleanup_graph.py --complete` for fresh start
   - Reduce `--max-commits` for git history loading
3. **Import errors**: Ensure all dependencies are installed in correct environment
   - Always use `conda activate neo4j-code-graph`
   - Check `pip list` for missing packages
4. **Connection failures**: Verify Neo4j credentials and network connectivity
   - Check `.env` file configuration
   - Test with `python -c "from utils import get_neo4j_config; print(get_neo4j_config())"`
5. **OpenMP conflicts on macOS**: Set `export KMP_DUPLICATE_LIB_OK=TRUE`
6. **Branch not found**: Script auto-detects main/master/HEAD branches
7. **Slow performance**: Ensure proper environment and GPU detection
8. **🚨 CI Failures**: Run `pre-commit run --all-files` before committing to prevent ALL CI failures (formatting, imports, style, typing)
9. **Type Checking**: mypy configuration is currently lenient to allow gradual type annotation adoption
10. **Pre-commit Hooks**: Use latest versions (black 25.1.0, isort 6.0.1, flake8 7.3.0, mypy 1.17.0)

## Commit Checklist

**🚨 MANDATORY SINGLE CHECK (replaces all individual checks):**
- [ ] **Pre-commit hooks pass**: `pre-commit run --all-files` (ALL checks must show "Passed")

**If pre-commit fails, fix with:**
- [ ] **Auto-fix formatting/imports**: `make format`
- [ ] **Re-run validation**: `pre-commit run --all-files`
- [ ] **Repeat until all checks pass**

**Standard Quality Checks:**
- [ ] Documentation updated if adding new features
- [ ] No sensitive data in commits (`.env` is gitignored)
- [ ] Environment activated: `conda activate neo4j-code-graph`

**❌ NEVER COMMIT if `pre-commit run --all-files` shows ANY failures!**

**✅ CI Success Guarantee: If pre-commit passes locally, CI will pass too!**

## Code Quality Guidelines

### Avoid Overused Terminology

**❌ NEVER use these meaningless terms in code comments or commit messages:**
- "OPTIMIZED" / "optimized" / "optimize"
- "ENHANCED" / "enhanced" / "enhance"
- "IMPROVED" / "improved" / "improve"
- "BETTER" / "better"
- "FASTER" / "faster"
- "EFFICIENT" / "efficient"

**✅ Instead, be specific about WHAT and WHY:**
```python
# ❌ Bad: Use optimized query for better performance
# ✅ Good: Use EXISTS clause to reduce failed MATCH operations

# ❌ Bad: Improved memory management
# ✅ Good: Clear GPU cache every 2 batches to prevent OOM

# ❌ Bad: Enhanced batch processing
# ✅ Good: Increase batch size from 100 to 500 to reduce database round-trips
```

**Rationale**: Terms like "optimized" become meaningless over time - everything could be argued to be "optimized" making the term completely useless for understanding actual changes.

### Neo4j connection hygiene (Driver/Session usage)

Always close Neo4j connections explicitly. Use context managers for both `Driver` and `Session`. Do not rely on destructors/GC to close connections.

Bad:
```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(uri, auth=(user, pwd))
session = driver.session(database=db)
session.run("RETURN 1").consume()
# driver and session leak if exceptions occur; deprecation warning in driver
```

Good:
```python
from neo4j import GraphDatabase

with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
    with driver.session(database=db) as session:
        session.run("RETURN 1").consume()
```

Also acceptable if you need a helper:
```python
from src.utils.common import create_neo4j_driver

with create_neo4j_driver(uri, user, pwd) as driver:
    with driver.session(database=db) as session:
        ...
```

### Consistency & Conventions (MANDATORY)
- Logging:
  - Use `logging.getLogger(__name__)` in every module; avoid `print()` (except CLI tools), prefer logger.
  - INFO for high-level progress; DEBUG for verbose details.
- Progress for long runs:
  - Use `tqdm` for batch loops (transformers, bulk writes). If `tqdm` missing, emit periodic logger messages.
- Neo4j connections:
  - Always `with GraphDatabase.driver(...)` and `with driver.session(...)`.
  - Load creds via `src.utils.common.get_neo4j_config()`; CLI args override `.env`; never hardcode `localhost`.
  - Verify schema before writes using `src.data.schema_management.ensure_constraints_exist_or_fail`.
- Constants & tunables:
  - Put tunables in `src/constants.py` and allow env overrides.
  - Keep naming consistent (e.g., `embedding_{EMBEDDING_TYPE}`; avoid stale names tied to removed features).
- Transformers:
  - Prefer GPU (CUDA)/MPS; batch inputs; avoid per-item inference; show progress with `tqdm`.
  - Keep model settings in `constants.py` for any active transformer workloads.
- Utilities reuse:
  - Reuse helpers in `src/utils` for configuration/logging/connection instead of duplicating logic.

### Deprecation policy (MANDATORY)
- Never ship or keep code that emits deprecation warnings from Neo4j, GDS, drivers, or libraries.
- If a deprecation warning appears in tests, scripts, or query output, replace the deprecated API/procedure/function with the documented alternative immediately.
- Do not suppress deprecation warnings; update the implementation and associated tests/queries so they are warning-free.
- Prefer the latest stable APIs in docs and examples to avoid future breakage.

## 🔧 AUTOMATED TOOLS SUMMARY

### 1. **Safe Commit Script** (RECOMMENDED)
```bash
./scripts/safe_commit.sh "Add new feature"
# ✅ Handles everything automatically
# ✅ Guarantees CI success
```

### 2. **Automatic Git Hook** (BACKUP PROTECTION)
```bash
git commit -m "message"
# ✅ Automatically validates before commit
# ✅ Blocks commits that would fail CI
```

### 3. **Manual Quality Checks**

```bash
# 🚨 MANDATORY: The only command you need before committing:
pre-commit run --all-files

# Fix issues automatically first:
make format  # Fixes black + isort violations

# Then verify everything passes:
pre-commit run --all-files

# ❌ NEVER commit if pre-commit shows any failures!

# Note: CI runs the exact same pre-commit hooks - perfect consistency
```
