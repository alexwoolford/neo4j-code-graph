# neo4j-code-graph

This repository contains a simple demonstration script for loading a Git
repository into a Neo4j database. It uses GraphCodeBERT to generate
embeddings for Java source files and methods. These embeddings are stored
on nodes in Neo4j so that they can be queried with Cypher or used with
Neo4j's vector search capabilities.

## Requirements

Install Python dependencies:

```bash
pip install gitpython transformers torch javalang neo4j python-dotenv
```

## Usage

Create a `.env` file with connection details for your Neo4j instance. You can
use `.env.example` as a starting point:

```bash
cp .env.example .env
# then edit .env with your credentials
```

If the `NEO4J_URI` in your `.env` file omits a port, the script
automatically uses `7687` which is the default for the Neo4j Bolt protocol.

Run the loader with a Git repository URL. For example, to load the
open-source Neo4j project:

```bash
python code_to_graph.py https://github.com/neo4j/neo4j.git
```

The script clones the repository, processes all `*.java` files, and
creates `File` and `Method` nodes with embedding vectors in Neo4j.
