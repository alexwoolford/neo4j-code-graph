# neo4j-code-graph

This repository contains a simple demonstration script for loading a Git
repository into a Neo4j database. It uses GraphCodeBERT to generate
embeddings for Java source files and methods. These embeddings are stored
on nodes in Neo4j so that they can be queried with Cypher or used with
Neo4j's vector search capabilities.

## Requirements

Install Python dependencies:

```bash
pip install gitpython transformers torch javalang neo4j
```

## Usage

Set environment variables for your Neo4j instance:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=secret
```

Run the loader with a Git repository URL. For example, to load the
open-source Neo4j project:

```bash
python code_to_graph.py https://github.com/neo4j/neo4j.git
```

The script clones the repository, processes all `*.java` files, and
creates `File` and `Method` nodes with embedding vectors in Neo4j.
