# Neo4j Code Graph

[![CI](https://github.com/alexwoolford/neo4j-code-graph/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/alexwoolford/neo4j-code-graph/actions/workflows/ci.yml?query=branch%3Amain)
[![codecov](https://codecov.io/gh/alexwoolford/neo4j-code-graph/graph/badge.svg?token=JDCC5T84OG)](https://codecov.io/gh/alexwoolford/neo4j-code-graph)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Last Commit](https://img.shields.io/github/last-commit/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/commits/main)
[![Issues](https://img.shields.io/github/issues/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/issues)
[![Pull Requests](https://img.shields.io/github/issues-pr/alexwoolford/neo4j-code-graph)](https://github.com/alexwoolford/neo4j-code-graph/pulls)

Turn your codebase into a queryable knowledge graph. Find security vulnerabilities, architectural bottlenecks, technical debt hotspots, and team coordination issues with simple Cypher queries.

👉 Full documentation: https://alexwoolford.github.io/neo4j-code-graph/

## Read the Docs

The full documentation lives on the site.

- Getting started: https://alexwoolford.github.io/neo4j-code-graph/neo4j-code-graph/0.1/getting-started.html
- Queries catalog: https://alexwoolford.github.io/neo4j-code-graph/neo4j-code-graph/0.1/queries/index.html
- Architecture: https://alexwoolford.github.io/neo4j-code-graph/neo4j-code-graph/0.1/architecture.html

## Quick Start

### 1. Setup
```bash
git clone https://github.com/alexwoolford/neo4j-code-graph
cd neo4j-code-graph

# Install the package with development tools (note the quotes for zsh)
pip install -e '.[dev]'

# Set up Neo4j connection
# Set your Neo4j URI (avoid hardcoded localhost in production)
# Example:
# export NEO4J_URI="bolt://10.0.1.27:7687"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="your_password"

# Optional but strongly recommended for faster CVE analysis
export NVD_API_KEY="your_nvd_api_key"
```

### 2. Analyze Your Codebase

Run the pipeline with Prefect (recommended):
```bash
# Option A: using the installed console script
code-graph-pipeline-prefect --repo-url https://github.com/your-org/your-repo

# Option B: run directly without installation
python -m src.pipeline.prefect_flow --repo-url https://github.com/your-org/your-repo
```

Or run individual steps via installed CLIs:
```bash
code-graph-code-to-graph /path/to/local/repo
code-graph-git-history /path/to/local/repo
code-graph-similarity --top-k 5 --cutoff 0.8
code-graph-centrality --algorithms pagerank betweenness degree --top-n 20 --write-back
code-graph-cve --risk-threshold 7.0 --max-hops 4
```



### 3. Query Your Data
Open Neo4j Browser or Bloom and run the business queries above. Copy/paste any query and modify for your needs.

## What Gets Analyzed

**Code Structure:**
- Files, directories, classes, interfaces, methods
- Inheritance relationships (extends, implements)
- Method calls and dependencies
- External library usage

**Git History:**
- All commits, authors, and file changes
- Co-change patterns between files
- Developer expertise mapping

**Security:**
- CVE vulnerabilities in dependencies
- Vulnerability impact through the codebase
- Security surface analysis

**Generated Insights:**
- Method importance scores (PageRank)
- Architectural bottlenecks (Betweenness Centrality)
- Code similarity clusters

## Graph Schema

The knowledge graph uses this data model:

![Neo4j Code Graph Schema](docs/schema.png)

## Project Structure

```
neo4j-code-graph/
├── src/                    # Core library code
│   ├── analysis/          # Code and git analysis
│   ├── security/          # CVE vulnerability analysis
│   ├── data/              # Schema and data management
│   └── utils/             # Common utilities
├── scripts/               # CLI tools
│   ├── code_to_graph.py          # Code structure analysis
│   ├── git_history_to_graph.py   # Git history analysis
│   ├── cve_analysis.py           # Security analysis
│   └── centrality_analysis.py    # Graph algorithms
├── cypher_templates_for_bloom.cypher  # Ready-to-use Bloom queries
├── examples/              # Business query examples
└── tests/                 # Test suite
```

## Configuration

Set environment variables or create a `.env` file:
```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j

# 🔑 IMPORTANT: NVD API key for CVE analysis (highly recommended)
# Get your free API key: https://nvd.nist.gov/developers/request-an-api-key
NVD_API_KEY=your_nvd_api_key

# Optional similarity defaults (can be overridden by CLI flags)
SIMILARITY_TOP_K=5    # or SIM_TOP_K
SIMILARITY_CUTOFF=0.8 # or SIM_CUTOFF

# Advanced tuning variables are available for power users; see `src/constants.py`.
```

> 💡 Without an NVD API key, CVE analysis will be slower (strict public rate limits). Get a free key at: https://nvd.nist.gov/developers/request-an-api-key

### Prefect UI (optional)

For a visual DAG and history, run a local Prefect server in another terminal:
```bash
prefect server start
```
Then run the flow as above. If you ever need to reset the ephemeral SQLite backing store:
```bash
prefect server reset-data
```

## Requirements

- Python 3.10+
- Neo4j 5.26+ (Community or Enterprise). For live tests we use 5.26-enterprise with APOC core and GDS.
- Git (for repository analysis)

## Development

### Contributing

When contributing code, please follow our [Coding Style Guide](CODING_STYLE_GUIDE.md) to maintain consistency across the codebase.

Key guidelines:
- Use helper functions from `utils.common` (logging, Neo4j connections, argument parsing)
- Follow established import patterns
- Maintain consistent error handling
- Run pre-commit checks before submitting

### Schema

- Method nodes use `method_signature` as the unique identifier.
- `Method.id` is required for Bloom and tooling compatibility.
- Constraints and indexes are created by `src/data/schema_management.py` and are invoked automatically in the pipeline.

### Temporal analysis

Use the module entry point for temporal analyses:

```bash
python -m src.analysis.temporal_analysis coupling --min-support 5 --create-relationships
python -m src.analysis.temporal_analysis hotspots --days 365 --min-changes 3 --top-n 15
```

### Logs and temp files

- Logs default to console; pass `--log-file .scratch/<name>.log` to persist.
- The `.scratch/` directory is gitignored for local artifacts.

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Live integration tests against Neo4j 5.26 with APOC core and GDS
Use `pytest -m live` with a configured Neo4j to run live tests.

# Run specific test categories
pytest tests/security/
pytest tests/integration/
```

Notes:
- The Prefect pipeline is idempotent. You can re-run on different repositories and load them into the same graph. Only `SIMILAR` relationships are cleaned prior to similarity calculations to avoid duplicates.
- APOC extended procedures are not used; only APOC core and standard GDS to maintain Aura compatibility.

## License

Licensed under the MIT License.
