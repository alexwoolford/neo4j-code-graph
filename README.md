# neo4j-code-graph

This repository contains scripts for loading Git repositories into a Neo4j database with advanced code analysis capabilities. It uses GraphCodeBERT to generate embeddings for Java source files and methods, creates similarity relationships between methods, and imports complete Git history for temporal analysis.

## Features

### Core Analysis Capabilities
- **📁 Enhanced Code Structure**: Loads Java files, methods, classes, and interfaces with rich metadata
- **🔗 Method Call Graphs**: Extracts and maps method invocation relationships (`CALLS`)
- **🏗️ Object-Oriented Analysis**: Class inheritance hierarchies (`EXTENDS`, `IMPLEMENTS`)
- **🎯 Method Similarity Detection**: Uses GraphCodeBERT embeddings + Neo4j GDS KNN
- **👥 Community Detection**: Groups related methods using Louvain algorithm  
- **📈 Git History Integration**: Complete commit history with developer and file change data
- **🔥 Advanced Hotspot Analysis**: Multi-factor complexity scoring (change frequency × complexity)
- **📊 Centrality Analysis**: PageRank, Betweenness, Degree centrality for importance ranking

### Performance & Scalability  
- **⚡ GPU Acceleration**: MPS (Apple Silicon) and CUDA support for embeddings
- **📦 Bulk Operations**: Optimized Neo4j loading with batching and indexing
- **🚀 Git History Optimization**: 15-30x faster file change processing
- **💾 Memory Efficient**: Dynamic batch sizing and cleanup for large repositories

### Export & Integration
- **📊 Flexible Export**: CSV export for external analysis tools
- **🔍 Rich Querying**: Advanced Cypher queries for architectural insights
- **🛠️ Developer Tools**: Comprehensive CLI tools with progress tracking

## Requirements

Install Python dependencies (versions pinned in `requirements.txt`):

```bash
pip install -r requirements.txt
```

For development tasks such as running the test suite:

```bash
pip install -r dev-requirements.txt
```

The `requirements.txt` file contains:

```
gitpython==3.1.44
transformers==4.53.2
torch==2.7.1
javalang==0.13.0
neo4j==5.28.1
graphdatascience==1.16
python-dotenv==1.1.1
tqdm==4.66.4
pandas==2.2.3
pyarrow>=17.0,<21.0
```

## Quick Start

### 1. Setup Environment

**Conda Environment (Recommended):**
```bash
# Create and activate environment
conda create -n neo4j-code-graph python=3.11
conda activate neo4j-code-graph

# Install dependencies
pip install -r requirements.txt
pip install -r dev-requirements.txt  # For development
```

**Environment Configuration:**
Create a `.env` file with your Neo4j connection details:

```bash
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j
```

### 2. Run Complete Pipeline

```bash
# Run the entire analysis pipeline on any Java repository
./run_pipeline.sh https://github.com/your-org/your-java-repo.git

# Or run individual components:

# Load code structure with embeddings
python code_to_graph.py https://github.com/neo4j/neo4j.git

# Load git history 
python git_history_to_graph.py https://github.com/neo4j/neo4j.git

# Create method similarities and communities
python create_method_similarity.py
```

## Scripts Overview

### `code_to_graph.py` - Enhanced Code Structure Analysis
Loads comprehensive Java source code structure into Neo4j:
- **Repository Processing**: Clones and parses Java files using `javalang`
- **Node Creation**: Creates `File`, `Method`, `Class`, `Interface`, and `Directory` nodes
- **Rich Metadata**: Method metrics (LOC, modifiers, visibility), class inheritance details
- **Method Calls**: Extracts and creates `CALLS` relationships between methods
- **OOP Relationships**: Maps class inheritance (`EXTENDS`) and interface implementation (`IMPLEMENTS`)
- **Embeddings**: Generates GraphCodeBERT embeddings for semantic similarity
- **GPU Optimization**: MPS and CUDA acceleration with optimized batch sizing

```bash
python code_to_graph.py <repo_url> \
  --uri bolt://localhost:7687 \
  --username neo4j \
  --password secret \
  --log-level INFO
```

### `git_history_to_graph.py`
Imports Git commit history:
- Extracts commit data using optimized git log commands
- Creates `Commit`, `Developer`, and `FileVer` nodes
- Links commits to files and developers
- Processes thousands of commits efficiently
- Supports CSV export for analysis

```bash
python git_history_to_graph.py <repo_url> \
  --branch master \
  --max-commits 1000 \
  --csv-export ./output
```

### `create_method_similarity.py`
Builds method similarity graph:
- Creates vector index on method embeddings
- Runs KNN algorithm to find similar methods
- Creates `SIMILAR` relationships with similarity scores
- Detects communities using Louvain algorithm
- Configurable similarity thresholds

```bash
python create_method_similarity.py \
  --top-k 10 \
  --cutoff 0.85 \
  --community-threshold 0.8
```

### Analysis Tool

#### `analyze.py` - Unified Analysis CLI
Consolidates all analysis functions into a single tool with subcommands:

**File Change Coupling Analysis:**
- Identifies files that frequently change together
- Creates `CO_CHANGED` relationships in the graph
- Calculates support and confidence metrics

```bash
# Analyze and create coupling relationships
python analyze.py coupling \
  --min-support 3 \
  --min-confidence 0.5 \
  --create-relationships
```

**Code Metrics:**
- Adds complexity metrics to File and Method nodes
- Calculates lines of code, method counts, file sizes
- Enriches graph with quantitative properties

```bash
# Add code metrics (requires local repository)
python analyze.py metrics \
  --repo-path /path/to/cloned/repo \
  --dry-run  # Preview changes first
```

**Enhanced Hotspot Analysis:**
- Multi-factor complexity scoring: change frequency × total complexity  
- Combines file size, OOP structure, coupling, and change patterns
- Risk categorization: HIGH_USAGE_LARGE, HIGH_COUPLING, PUBLIC_API
- Actionable insights with specific refactoring recommendations

```bash
# Find enhanced hotspots with multi-factor complexity scoring
python analyze.py hotspots \
  --days 180 \
  --min-changes 5 \
  --top-n 25
```

### `centrality_analysis.py` - Architectural Importance Analysis
Identifies structurally important code elements using graph algorithms:

**Centrality Algorithms:**
- **PageRank**: Methods central in the call ecosystem (widely used utilities)
- **Betweenness**: Critical connectors and architectural bottlenecks
- **Degree Centrality**: Hub methods (orchestrators) vs Authority methods (utilities)  
- **HITS**: Distinguishes between hubs and authorities in the call graph

**Use Cases:**
- Focus optimization efforts on high-impact methods
- Identify architectural bottlenecks and single points of failure
- Guide testing priorities for critical code paths
- Understand which methods are most central to system behavior

```bash
# Run all centrality algorithms
python centrality_analysis.py --algorithms pagerank betweenness degree hits

# Focus on specific algorithms with custom parameters
python centrality_analysis.py \
  --algorithms pagerank betweenness \
  --top-n 15 \
  --write-back  # Save scores to Method nodes
```

### Utility Scripts

#### `cleanup_graph.py`
Flexible cleanup tool with two modes:

**Selective Cleanup (Default):**
- Cleans up `SIMILAR` relationships and community properties
- Preserves expensive embeddings and core data
- Useful for re-running analysis with different parameters

**Complete Database Reset:**
- Deletes ALL nodes, relationships, indexes, and constraints
- Memory-efficient batched deletion for large databases
- Safety confirmation prompts

```bash
# Selective cleanup (default)
python cleanup_graph.py --dry-run
python cleanup_graph.py

# Complete database reset
python cleanup_graph.py --complete
python cleanup_graph.py --complete --confirm  # Skip confirmation
```

## Graph Schema

The enhanced graph schema captures comprehensive code structure, object-oriented relationships, and temporal evolution:

### **Node Types**

**📁 Code Structure Nodes:**
- `Directory`: Repository directories (`path`)
- `File`: Java files (`path`, `total_lines`, `code_lines`, `method_count`, `class_count`, `interface_count`)
- `Method`: Java methods (`name`, `file`, `line`, `class`, `estimated_lines`, `is_static`, `is_public`, `is_private`, `return_type`, `modifiers`, `embedding`, `similarityCommunity`)
- `Class`: Java classes (`name`, `file`, `line`, `estimated_lines`, `is_abstract`, `is_final`, `modifiers`)
- `Interface`: Java interfaces (`name`, `file`, `line`, `method_count`, `modifiers`)

**👥 Git History Nodes:**
- `Developer`: Git authors (`name`, `email`)
- `Commit`: Git commits (`sha`, `message`, `date`)
- `FileVer`: File versions at specific commits (`path`, `sha`)

### **Relationship Types**

**🏗️ Structural Relationships:**
- `(:Directory)-[:CONTAINS]->(:Directory|File)`: Directory hierarchy
- `(:File)-[:DECLARES]->(:Method)`: File contains methods
- `(:File)-[:DEFINES]->(:Class|Interface)`: File defines classes/interfaces
- `(:Class|Interface)-[:CONTAINS_METHOD]->(:Method)`: Class/interface contains methods

**🔗 Object-Oriented Relationships:**
- `(:Class)-[:EXTENDS]->(:Class)`: Class inheritance
- `(:Interface)-[:EXTENDS]->(:Interface)`: Interface inheritance  
- `(:Class)-[:IMPLEMENTS]->(:Interface)`: Interface implementation

**📞 Behavioral Relationships:**
- `(:Method)-[:CALLS {type}]->(:Method)`: Method invocations with call type (`same_class`, `static`, `instance`)
- `(:Method)-[:SIMILAR {score}]->(:Method)`: Semantic similarity with confidence score

**📈 Temporal & Analysis Relationships:**
- `(:File)-[:CO_CHANGED {support, confidence}]->(:File)`: Files that change together
- `(:Developer)-[:AUTHORED]->(:Commit)`: Commit authorship
- `(:Commit)-[:CHANGED]->(:FileVer)`: Commit changes file version
- `(:FileVer)-[:OF_FILE]->(:File)`: File version belongs to file

### **Enhanced Properties**

**Method Metrics:**
- `estimated_lines`, `is_static`, `is_abstract`, `is_final`, `is_private`, `is_public`
- `return_type`, `modifiers[]`, `containing_type`
- Centrality scores: `pagerank_score`, `betweenness_score`, `out_degree`, `in_degree`

**Class/Interface Metrics:**  
- `estimated_lines`, `is_abstract`, `is_final`, `modifiers[]`, `method_count`

**File Complexity Metrics:**
- `total_lines`, `code_lines`, `method_count`, `class_count`, `interface_count`

## Performance

The scripts are highly optimized for large repositories and modern hardware:

### **GPU Optimizations**
- **Apple Silicon**: Optimized batch sizes (256) with MPS high-performance mode
- **CUDA**: Automatic detection with mixed-precision training support
- **Memory management**: Efficient cache clearing and garbage collection
- **4x performance improvement** over default settings

### **Git History Loading**
- **Optimized bulk operations**: 3-step CREATE vs 5-step MERGE (15-30x faster)
- **Large batch processing**: 25K records per batch vs 10K default  
- **Memory-efficient**: Handles large repositories without memory issues
- **Progress reporting**: Real-time ETA and throughput monitoring

### **General Performance**
- **Git extraction**: ~9,600 commits/sec using optimized git log commands
- **Bulk loading**: UNWIND queries with batched operations
- **Smart fallbacks**: Automatic branch detection (main/master/HEAD)
- **Constraints and indexes**: Optimized for cloud Neo4j performance

## Example Queries

### **🏗️ Object-Oriented Architecture Analysis**
```cypher
// Find deep inheritance hierarchies (potential design complexity)
MATCH path = (leaf:Class)-[:EXTENDS*]->(root:Class)
WHERE NOT (root)-[:EXTENDS]->()
WITH leaf, root, length(path) as depth
WHERE depth > 3
RETURN leaf.name, root.name, depth, leaf.file
ORDER BY depth DESC LIMIT 10

// Find interfaces with many implementations (key abstractions)
MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface)
WITH i, count(c) as implementations, collect(c.name) as classes
WHERE implementations > 3
RETURN i.name, implementations, classes, i.file
ORDER BY implementations DESC

// Find classes that implement multiple interfaces (complexity indicators)
MATCH (c:Class)-[:IMPLEMENTS]->(i:Interface)
WITH c, count(i) as interface_count, collect(i.name) as interfaces
WHERE interface_count > 2
RETURN c.name, interface_count, interfaces, c.file
ORDER BY interface_count DESC
```

### **📞 Method Call Graph Analysis**
```cypher
// Find methods with highest outgoing calls (potential god methods)
MATCH (m:Method)-[:CALLS]->()
WITH m, count(*) as outgoing_calls
WHERE outgoing_calls > 10
RETURN m.class + "." + m.name as method, 
       outgoing_calls, m.estimated_lines, m.file
ORDER BY outgoing_calls DESC LIMIT 15

// Find most called methods (critical utilities)
MATCH ()-[:CALLS]->(m:Method)
WITH m, count(*) as incoming_calls
WHERE incoming_calls > 5
RETURN m.class + "." + m.name as method, 
       incoming_calls, m.is_static, m.is_public, m.file
ORDER BY incoming_calls DESC LIMIT 15

// Analyze call patterns between classes
MATCH (caller:Method)-[:CALLS]->(callee:Method)
WHERE caller.class <> callee.class
WITH caller.class as from_class, callee.class as to_class, count(*) as call_count
WHERE call_count > 3
RETURN from_class, to_class, call_count
ORDER BY call_count DESC LIMIT 20
```

### **🎯 Centrality & Importance Analysis**
```cypher
// Find architecturally most important methods (if centrality scores exist)
MATCH (m:Method)
WHERE m.pagerank_score IS NOT NULL
RETURN m.class + "." + m.name as method,
       m.pagerank_score, m.betweenness_score, 
       m.out_degree, m.in_degree, m.file
ORDER BY m.pagerank_score DESC LIMIT 10

// Find critical connector methods (high betweenness)
MATCH (m:Method)
WHERE m.betweenness_score IS NOT NULL AND m.betweenness_score > 0
RETURN m.class + "." + m.name as method,
       m.betweenness_score, m.estimated_lines, m.file
ORDER BY m.betweenness_score DESC LIMIT 10
```

### **🔥 Enhanced Hotspot Analysis**
```cypher
// Find complex files with frequent changes (manual hotspot calculation)
MATCH (f:File)
OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
WHERE c.date >= datetime() - duration('P180D')  // Last 6 months
WITH f, count(DISTINCT c) as changes
WHERE changes >= 3 AND f.total_lines >= 100
WITH f, changes, 
     // Multi-factor complexity scoring
     (f.total_lines + (f.method_count * 10) + (f.class_count * 50)) as complexity,
     (changes * (f.total_lines + (f.method_count * 10) + (f.class_count * 50))) as hotspot_score
RETURN f.path, changes, f.total_lines, f.method_count, f.class_count,
       complexity, hotspot_score
ORDER BY hotspot_score DESC LIMIT 15

// Find risky public methods (high usage + large size)
MATCH (m:Method)
WHERE m.is_public = true
OPTIONAL MATCH ()-[calls:CALLS]->(m)
WITH m, count(calls) as usage_count
WHERE usage_count > 5 AND m.estimated_lines > 20
RETURN m.class + "." + m.name as method,
       usage_count, m.estimated_lines, m.file
ORDER BY (usage_count * m.estimated_lines) DESC LIMIT 10
```

### **📊 Code Similarity & Duplication**
```cypher
// Find most similar methods (potential duplicates)
MATCH (m1:Method)-[s:SIMILAR]->(m2:Method)
WHERE s.score > 0.95
RETURN m1.class + "." + m1.name as method1,
       m2.class + "." + m2.name as method2, 
       s.score, m1.file, m2.file
ORDER BY s.score DESC LIMIT 10

// Find large similarity communities (refactoring opportunities)
MATCH (m:Method)
WHERE m.similarityCommunity IS NOT NULL
WITH m.similarityCommunity as community, collect(m) as methods
WHERE size(methods) > 5
RETURN community, size(methods) as method_count,
       [m IN methods[0..3] | m.class + "." + m.name] as sample_methods
ORDER BY method_count DESC LIMIT 10
```

### **📈 Temporal & Change Analysis**
```cypher
// Find files that frequently change together (coupling)
MATCH (f1:File)-[co:CO_CHANGED]->(f2:File)
WHERE co.support > 5
RETURN f1.path, f2.path, co.support, co.confidence
ORDER BY co.support DESC LIMIT 15

// Analyze developer activity patterns
MATCH (d:Developer)-[:AUTHORED]->(c:Commit)
WHERE c.date >= datetime() - duration('P90D')  // Last 3 months
RETURN d.name, count(c) as recent_commits
ORDER BY recent_commits DESC LIMIT 10
```

### File Change Coupling
```cypher
// Find files with strongest change coupling
MATCH (f1:File)-[co:CO_CHANGED]->(f2:File)
RETURN f1.path, f2.path, co.support, co.confidence
ORDER BY co.support DESC LIMIT 10

// Find unexpected couplings (high support, different directories)
MATCH (f1:File)-[co:CO_CHANGED]->(f2:File)
WHERE co.support >= 5 
  AND split(f1.path, '/')[0] <> split(f2.path, '/')[0]
RETURN f1.path, f2.path, co.support, co.confidence
ORDER BY co.support DESC
```

### Hotspot Analysis
```cypher
// Find largest files that change frequently (hotspots)
MATCH (f:File)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
WHERE f.total_lines > 200
WITH f, count(c) as changes
WHERE changes >= 5
RETURN f.path, f.total_lines, changes, 
       (changes * f.total_lines) as hotspot_score
ORDER BY hotspot_score DESC LIMIT 15

// Find files with high change density
MATCH (f:File)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
WHERE f.total_lines IS NOT NULL AND f.total_lines > 0
WITH f, count(c) as changes
RETURN f.path, f.total_lines, changes,
       round((changes * 100.0) / f.total_lines, 2) as changes_per_100_lines
ORDER BY changes_per_100_lines DESC LIMIT 15
```

### Architecture Insights
```cypher
// Find files that are both large and highly coupled
MATCH (f:File)-[co:CO_CHANGED]->(other:File)
WHERE f.total_lines > 300
WITH f, count(co) as coupling_count, sum(co.support) as total_coupling
RETURN f.path, f.total_lines, coupling_count, total_coupling
ORDER BY (f.total_lines * coupling_count) DESC LIMIT 10
```

## Configuration Options

All scripts support:
- `--uri`: Neo4j connection URI
- `--username/--password`: Authentication  
- `--database`: Target database name
- `--log-level`: Logging verbosity (DEBUG, INFO, WARNING, ERROR)
- `--log-file`: Write logs to file

Script-specific options:
- `code_to_graph.py`: No additional options
- `git_history_to_graph.py`: `--branch`, `--max-commits`, `--csv-export`
- `create_method_similarity.py`: `--top-k`, `--cutoff`, `--community-threshold`, `--no-knn`, `--no-louvain`

## Development

Run tests:
```bash
python -m pytest tests/ -v
```

Check code style:
```bash
flake8 --max-line-length=100
```

The project follows standard Python conventions with comprehensive test coverage for core functionality.
