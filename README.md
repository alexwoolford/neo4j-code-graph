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

Create a `.env` file with your Neo4j connection details:

```bash
NEO4J_URI=bolt://localhost:7687
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

### `cleanup_graph.py`
Safely removes analysis results:
- Cleans up `SIMILAR` relationships  
- Removes community properties
- Preserves expensive embeddings and code structure
- Includes dry-run mode for safety

```bash
python cleanup_graph.py --dry-run
python cleanup_graph.py  # Actually perform cleanup
```

## Graph Schema

The scripts create the following node types and relationships:

**Nodes:**
- `Directory`: Repository directories (`path`)
- `File`: Java source files (`path`, `embedding`, `embedding_type`)
- `Method`: Java methods (`name`, `file`, `line`, `class`, `embedding`, `embedding_type`, `similarityCommunity`)
- `Developer`: Git authors (`name`, `email`)
- `Commit`: Git commits (`sha`, `message`, `date` as `datetime`)
- `FileVer`: File versions at specific commits (`path`, `sha`)

**Relationships:**
- `CONTAINS`: Directory contains files/subdirectories
- `DECLARES`: File declares methods
- `CALLS`: Method calls another method  
- `SIMILAR`: Methods are similar (with `score` property)
- `AUTHORED`: Developer authored commit
- `CHANGED`: Commit changed file version
- `OF_FILE`: File version belongs to file

## Performance

The scripts are optimized for large repositories:
- **Git extraction**: ~2,000 commits/sec using direct git commands
- **Bulk loading**: UNWIND queries for efficient Neo4j writes
- **Batch processing**: Configurable batch sizes to manage memory
- **Constraints**: Unique constraints and indexes for performance
- **Parallel embedding**: GPU acceleration when available

## Example Queries

After loading a repository, explore the graph:

```cypher
// Find most similar methods
MATCH (m1:Method)-[s:SIMILAR]->(m2:Method)
RETURN m1.name, m2.name, s.score
ORDER BY s.score DESC LIMIT 10

// Find prolific developers
MATCH (d:Developer)-[:AUTHORED]->(c:Commit)
RETURN d.name, d.email, count(c) as commits
ORDER BY commits DESC LIMIT 10

// Find methods in the same community
MATCH (m:Method)
WHERE m.similarityCommunity = 42
RETURN m.name, m.file, m.class

// Find files changed most frequently
MATCH (f:File)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
RETURN f.path, count(c) as changes
ORDER BY changes DESC LIMIT 10
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
