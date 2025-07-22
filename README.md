# neo4j-code-graph

This repository contains scripts for loading Git repositories into a Neo4j database with advanced code analysis capabilities. It uses GraphCodeBERT to generate embeddings for Java source files and methods, creates similarity relationships between methods, and imports complete Git history for temporal analysis.

## Features

- **Code Structure Analysis**: Loads Java files and methods with embeddings
- **Method Similarity Detection**: Uses Neo4j GDS KNN to find similar methods
- **Community Detection**: Groups related methods using Louvain algorithm  
- **Git History Integration**: Imports complete commit history and developer data
- **Performance Optimized**: Uses bulk operations and optimized git extraction
- **Flexible Export**: Can export to CSV or load directly to Neo4j

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

### `code_to_graph.py`
Loads Java source code into Neo4j:
- Clones the repository
- Parses Java files using `javalang`  
- Generates embeddings using GraphCodeBERT
- Creates `File`, `Method`, and `Directory` nodes
- Links method calls with `CALLS` relationships
- Preserves directory structure

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

**Hotspot Analysis:**
- Implements Adam Tornhill's hotspot analysis
- Combines change frequency with code complexity
- Identifies problematic code areas requiring attention

```bash
# Find code hotspots from last 6 months
python analyze.py hotspots \
  --days 180 \
  --min-changes 5 \
  --top-n 25
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

The scripts create the following node types and relationships:

**Nodes:**
- `Directory`: Repository directories (`path`)
- `File`: Java source files (`path`, `total_lines`, `code_lines`, `method_count`)
- `Method`: Java methods (`name`, `file`, `line`, `class`, `embedding`, `similarityCommunity`, `estimated_lines`)
- `Developer`: Git authors (`name`, `email`)
- `Commit`: Git commits (`sha`, `message`, `date`)
- `FileVer`: File versions at specific commits (`path`, `sha`)

**Relationships:**
- `CONTAINS`: Directory contains files/subdirectories
- `DECLARES`: File declares methods
- `CALLS`: Method calls another method  
- `SIMILAR`: Methods are similar (with `score` property)
- `CO_CHANGED`: Files that frequently change together (with `support`, `confidence`)
- `AUTHORED`: Developer authored commit
- `CHANGED`: Commit changed file version
- `OF_FILE`: File version belongs to file

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

### **Code Similarity & Architecture**
```cypher
// Find most similar methods with context
MATCH (m1:Method)-[s:SIMILAR]->(m2:Method)
WHERE s.score > 0.95
RETURN m1.class + "." + m1.name as method1,
       m2.class + "." + m2.name as method2, 
       s.score, m1.file, m2.file
ORDER BY s.score DESC LIMIT 10

// Analyze similarity communities
MATCH (m:Method)
WHERE m.similarityCommunity IS NOT NULL
WITH m.similarityCommunity as community, collect(m) as methods
WHERE size(methods) > 5
RETURN community, size(methods) as method_count,
       [m IN methods[0..3] | m.class + "." + m.name] as sample_methods
ORDER BY method_count DESC

// Find cross-package similar methods (potential refactoring opportunities)
MATCH (m1:Method)-[s:SIMILAR]->(m2:Method)
WHERE s.score > 0.90 
  AND split(m1.file, '/')[0] <> split(m2.file, '/')[0]
RETURN m1.file, m2.file, m1.name, m2.name, s.score
ORDER BY s.score DESC LIMIT 15
```

### Change Frequency Analysis  
```cypher
// Find files changed most frequently
MATCH (f:File)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
RETURN f.path, count(c) as changes
ORDER BY changes DESC LIMIT 10

// Find prolific developers
MATCH (d:Developer)-[:AUTHORED]->(c:Commit)
RETURN d.name, d.email, count(c) as commits
ORDER BY commits DESC LIMIT 10
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
