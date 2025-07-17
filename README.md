# neo4j-code-graph

This repository contains a simple demonstration script for loading a Git
repository into a Neo4j database. It uses GraphCodeBERT to generate
embeddings for Java source files and methods. These embeddings are stored
on nodes in Neo4j so that they can be queried with Cypher or used with
Neo4j's vector search capabilities.

## Requirements

Install Python dependencies (versions pinned in `requirements.txt`):

```bash
pip install -r requirements.txt
```

The `requirements.txt` file pins the library versions used by this
project:

```
gitpython==3.1.44
transformers==4.53.2
torch==2.7.1
javalang==0.13.0
neo4j==5.28.1
graphdatascience==1.16
python-dotenv==1.1.1
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

You can also override the Neo4j connection details on the command line:

```bash
python code_to_graph.py https://github.com/neo4j/neo4j.git \
  --uri bolt://localhost:7687 --username neo4j --password secret --database neo4j
```

The script clones the repository, processes all `*.java` files, and
creates `File` and `Method` nodes with embedding vectors in Neo4j.

### Build similarity relationships

Once the graph contains method embeddings you can generate `SIMILAR`
relationships between the closest methods using the Graph Data Science
KNN algorithm:

```bash
python create_method_similarity.py
```

You can specify a different Neo4j connection or adjust the kNN parameters:

```bash
python create_method_similarity.py --top-k 10 --cutoff 0.85 \
  --uri bolt://localhost:7687 --username neo4j --password secret
```

This script creates a vector index on the `Method.embedding` property if
one does not already exist and then writes `SIMILAR` relationships with a
`score` property for pairs of methods that exceed the similarity cutoff.

## License

This project is licensed under the [MIT License](LICENSE).

