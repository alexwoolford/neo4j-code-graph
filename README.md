# Neo4j Code Graph

Advanced code analysis platform that creates comprehensive knowledge graphs from ANY codebase. Works with Java, Python, JavaScript, Go, Rust, C++, C#, and more - no hardcoded mappings required.

## 📁 Project Structure

The project is organized into logical directories following Python best practices:

```
neo4j-code-graph/
├── src/                    # Core library code
│   ├── analysis/          # Analysis modules
│   │   ├── code_analysis.py      # Code structure extraction
│   │   ├── git_analysis.py       # Git history analysis
│   │   ├── centrality.py         # Graph centrality algorithms
│   │   ├── similarity.py         # Method similarity analysis
│   │   └── combined_analysis.py  # Multi-purpose analysis tool
│   ├── security/          # Vulnerability analysis
│   │   ├── cve_analysis.py       # Universal CVE analysis
│   │   └── cve_cache_manager.py  # CVE data management
│   ├── data/              # Data management
│   │   └── schema_management.py  # Neo4j schema setup
│   ├── utils/             # Common utilities
│   │   ├── common.py             # Shared functions
│   │   ├── neo4j_utils.py        # Neo4j connection utils
│   │   └── cleanup.py            # Database cleanup
│   └── pipeline/          # Pipeline orchestration (future)
├── scripts_new/           # CLI tools
│   ├── run_pipeline.sh           # Main pipeline orchestrator
│   ├── code_to_graph.py          # CLI: Code analysis
│   ├── git_history_to_graph.py   # CLI: Git history
│   ├── analyze.py                # CLI: Combined analysis
│   ├── centrality_analysis.py    # CLI: Centrality analysis
│   ├── create_method_similarity.py # CLI: Similarity analysis
│   ├── cve_analysis.py           # CLI: CVE analysis
│   ├── schema_management.py      # CLI: Schema management
│   └── cleanup_graph.py          # CLI: Database cleanup
├── tests/                 # Test suite
├── examples/              # Example scripts and queries
├── docs/                  # Documentation
├── config/                # Configuration files
│   ├── requirements.txt
│   ├── dev-requirements.txt
│   └── setup.cfg
├── data/                  # Runtime data
│   └── cve_cache/        # CVE data cache
├── README.md
├── AGENTS.md
├── LICENSE
└── .gitignore
```

**Key Benefits:**
- **🔍 Clear Separation**: Library code (`src/`) vs CLI tools (`scripts_new/`)
- **📦 Modular Design**: Logical grouping by functionality
- **🧪 Better Testing**: Easier to test individual modules
- **🛠️ Maintainability**: Professional project organization
- **📚 Extensibility**: Easy to add new analysis modules

## ✨ Features

- **📁 Universal Code Structure**: Loads files, methods, classes, and interfaces with rich metadata across all programming languages
- **🔗 Object-Oriented Relationships**: Maps EXTENDS, IMPLEMENTS, CONTAINS_METHOD relationships
- **📞 Call Graph Analysis**: Creates detailed method call networks with call types and context
- **🧠 GraphCodeBERT Embeddings**: Semantic method similarity analysis using ML models
- **🏘️ Community Detection**: Identifies cohesive code modules using graph algorithms
- **📊 Centrality Analysis**: PageRank, Betweenness, and Degree centrality for architectural insights
- **📈 Git History Integration**: Temporal analysis of code evolution and developer contributions
- **🔥 Hotspot Analysis**: Identifies problematic code areas using frequency × complexity scoring
- **🔄 Change Coupling**: Discovers files that change together using association rule mining
- **🛡️ Universal CVE Analysis**: Language-agnostic vulnerability impact analysis with NO hardcoded mappings
- **📦 Bulk Operations**: Efficient Neo4j loading with batching and indexing
- **🚀 Git History Analysis**: Efficient bulk loading with progress tracking

## 🛡️ Universal CVE Analysis

Our CVE analysis works with ANY programming language and dependency ecosystem:

### 🌐 Language-Agnostic Design
- **No Hardcoded Mappings**: Dynamically extracts dependencies from any codebase
- **Universal Pattern Matching**: Works with Java, Python, Node.js, Go, Rust, C++, C#, PHP, Ruby
- **Smart Content Analysis**: Uses CPE data and textual analysis for CVE relevance
- **Multi-Modal Neo4j**: Combines graph traversal, vector search, Lucene search, and algorithms

### 🚀 Quick Start: Universal CVE Analysis

```bash
# 1. Run the complete pipeline on ANY codebase
./scripts_new/run_pipeline.sh https://github.com/your-org/your-repo.git

# 2. Get NVD API key (recommended for production use)
# Visit: https://nvd.nist.gov/developers/request-an-api-key
export NVD_API_KEY="your_api_key_here"

# 3. Run universal vulnerability analysis
python scripts_new/cve_analysis.py \
  --risk-threshold 7.0 \
  --max-hops 4

# 4. Run interactive demo showing all Neo4j access patterns
python examples/cve_demo_queries.py
```

**Note**: Without an API key, rate limits apply (10 requests per minute). With a key, you get 50 requests per 30 seconds.

## 🎯 Multi-Modal Neo4j Access Patterns

The CVE analysis demonstrates all major Neo4j capabilities:

### 1. **Graph Traversal**
```cypher
// Find dependency paths from vulnerabilities to public APIs
MATCH (cve:CVE)-[:AFFECTS]->(ed:ExternalDependency)
MATCH path = (api_file:File)-[:DEPENDS_ON*1..4]->(ed)
WHERE api_file.package CONTAINS "api"
RETURN cve.cve_id, api_file.path, length(path) as distance
ORDER BY cve.cvss_score DESC, distance ASC
```

### 2. **Vector Search**
```cypher
// Find components similar to vulnerable ones using embeddings
CALL db.index.vector.queryNodes('component_embeddings', 5, $vuln_embedding)
YIELD node, score
WHERE score > 0.8
RETURN node.name, score
```

### 3. **Lucene Full-Text Search**
```cypher
// Search CVE descriptions for attack patterns
CALL db.index.fulltext.queryNodes('cve_description_index', 
  'remote code execution OR sql injection') 
YIELD node, score
WHERE score > 0.5
RETURN node.cve_id, node.description, score
```

### 4. **Graph Algorithms**
```cypher
// Use PageRank to find most critical dependencies
CALL gds.pageRank.stream('dependency-graph')
YIELD nodeId, score
MATCH (n) WHERE id(n) = nodeId
RETURN n.name, score ORDER BY score DESC
```

### 5. **Hybrid Queries**
```cypher
// Combine multiple signals for comprehensive risk assessment
MATCH (cve:CVE)-[:AFFECTS]->(comp:Component)
WHERE cve.cvss_score >= 7.0
// Graph traversal + Vector similarity + Text analysis
OPTIONAL MATCH path = (api:File)-[:DEPENDS_ON*1..3]->(ed)-[:RESOLVED_TO]->(comp)
WITH cve, comp, count(path) AS exposure,
     (cve.cvss_score * exposure * similarity_score) AS risk
RETURN cve.cve_id, comp.name, risk ORDER BY risk DESC
```

## 📊 Universal Graph Schema

The enhanced graph schema works with any programming language:

```
(:File)-[:DEPENDS_ON]->(:ExternalDependency)-[:RESOLVED_TO]->(:Component)
(:CVE)-[:AFFECTS]->(:Component)
(:Method)-[:CALLS]->(:Method)
(:Class)-[:EXTENDS|IMPLEMENTS]->(:Class|Interface)
(:File)-[:DEFINES]->(:Class|Interface|Method)
```

### **Universal Properties**
- **Language Detection**: Automatic language identification
- **Dependency Extraction**: Works with any package manager or import system
- **Vulnerability Mapping**: Dynamic CVE-to-dependency matching
- **Impact Analysis**: Multi-hop dependency impact calculation

## Quick Start

```bash
# Clone and setup
git clone <this-repo>
cd neo4j-code-graph

# Install dependencies
pip install -r config/requirements.txt

# Set up Neo4j connection (create .env file)
NEO4J_URI=your_neo4j_uri
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j

# Run complete analysis pipeline
./scripts_new/run_pipeline.sh https://github.com/your-org/your-repo.git
```

## 🚀 Analysis Tools

### Code Structure Analysis

Extracts comprehensive code structure from any programming language:

```bash
python scripts_new/code_to_graph.py <repository-url>
```

**Features:**
- **Universal Language Support**: Java, Python, JavaScript, Go, Rust, C++, C#, PHP, Ruby
- **Rich Metadata**: Lines of code, complexity metrics, method signatures
- **GraphCodeBERT Embeddings**: 768-dimensional vectors for semantic similarity
- **Dependency Tracking**: Import/include statements across all languages
- **Bulk Loading**: Efficient batch processing for large codebases

### Git History Analysis

```bash
python scripts_new/git_history_to_graph.py <repository-url>
```

**Features:**
- Extracts commit data using git log commands
- Links commits to file changes and developers
- Supports branch selection and commit filtering
- Bulk operations for performance at scale

### Hotspot Analysis

```bash
# Find code hotspots with multi-factor complexity scoring
python scripts_new/analyze.py hotspots --days 365 --min-changes 3 --top-n 15
```

**Hotspot Analysis:**
- Combines change frequency with multiple complexity factors
- Identifies files that change often AND are complex
- Focus optimization efforts on high-impact areas
- Multi-dimensional scoring: size + OOP complexity + coupling

### Centrality Analysis

```bash
# Identify architecturally important methods
python scripts_new/centrality_analysis.py --algorithms pagerank betweenness --top-n 20 --write-back
```

**Centrality Metrics:**
- **PageRank**: Overall importance in the call graph
- **Betweenness**: Critical connectors and potential bottlenecks  
- **Degree**: Most connected methods (high fan-in/fan-out)

### `git_history_to_graph.py` - Git History Analysis  

```