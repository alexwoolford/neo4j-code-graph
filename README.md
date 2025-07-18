# neo4j-code-graph

This repository contains a simple demonstration script for loading a Git
repository into a Neo4j database. It uses GraphCodeBERT to generate
embeddings for Java source files and methods. These embeddings are stored
on nodes in Neo4j so that they can be queried with Cypher or used with
Neo4j's vector search capabilities. The loader creates `File` and
`Method` nodes linked by `CALLS` relationships.

## Requirements

Install Python dependencies (versions pinned in `requirements.txt`):

```bash
pip install -r requirements.txt
```

For development tasks such as running the test suite, you can also install
packages from `dev-requirements.txt`:

```bash
pip install -r dev-requirements.txt
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
tqdm==4.66.4
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

The script accepts several options when you want to override the connection
information from your `.env` file:

```bash
python code_to_graph.py <repo_url> \
  --uri bolt://localhost:7687 \
  --username neo4j \
  --password secret \
  --database neo4j \
  --log-level INFO
```

Where:

- `--uri` sets the Neo4j Bolt URI.
- `--username` and `--password` supply authentication credentials.
- `--database` selects the target database.
- `--log-level` controls logging verbosity (DEBUG, INFO, WARNING, ERROR).
- `--log-file` optionally writes logs to a file in addition to the console.

The script clones the repository, processes all `*.java` files, and
creates `File` nodes for each source file and `Method` nodes for each
method. Method invocations are linked with `CALLS` relationships, and
each node stores an embedding vector for similarity search. Directory
structure is preserved with `Directory` nodes and `CONTAINS` relationships.
A progress bar is displayed while processing files.

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

Where:

- `--top-k` sets the number of nearest neighbors to find for each method (default: 5).
- `--cutoff` sets the minimum similarity score threshold (default: 0.8).
- `--log-level` controls logging verbosity.
- `--log-file` optionally writes logs to a file.

This script creates a vector index on the `Method.embedding` property if
one does not already exist and then writes `SIMILAR` relationships with a
`score` property for pairs of methods that exceed the similarity cutoff.

## Graph Schema

The scripts create the following node types and relationships:

**Nodes:**
- `Directory`: Represents directories in the repository structure
  - Properties: `path` (string)
- `File`: Represents Java source files  
  - Properties: `path` (string), `embedding` (vector), `embedding_type` (string)
- `Method`: Represents Java methods
  - Properties: `name` (string), `file` (string), `line` (integer), `class` (string, optional), `embedding` (vector), `embedding_type` (string)

**Relationships:**
- `CONTAINS`: Directory contains subdirectories or files
- `DECLARES`: File declares methods
- `CALLS`: Method calls another method
- `SIMILAR`: Methods are similar based on embedding similarity (created by similarity script)

## Example queries

After loading a repository you can explore the graph using Neo4j Browser or
Neo4j Desktop. Connect using the Bolt URI and credentials defined in your
`.env` file. A local Neo4j instance is typically available at
`bolt://localhost:7687`, which you can access via [Neo4j Browser](https://neo4j.com/developer/neo4j-browser/) by navigating to
`http://localhost:7474` in your web browser or by adding a connection in
Neo4j Desktop.

The following Cypher snippets demonstrate how to inspect the different node
and relationship types created by the scripts:

```cypher
// List a few files that were processed
MATCH (f:File)
RETURN f.path
LIMIT 10;

// Show methods declared in a specific file
MATCH (f:File {path: $path})-[:DECLARES]->(m:Method)
RETURN m.name, m.line, m.class
LIMIT 10;

// Examine method similarity relationships
MATCH (m1:Method)-[s:SIMILAR]->(m2:Method)
RETURN m1.name, m1.class, m2.name, m2.class, s.score
ORDER BY s.score DESC
LIMIT 10;

// Follow a chain of method calls
MATCH p=(m:Method {name: $method})-[:CALLS*1..3]->(called)
RETURN called.name, called.class 
LIMIT 10;

// Find methods in the same class that are similar
MATCH (m1:Method)-[s:SIMILAR]->(m2:Method)
WHERE m1.class = m2.class AND m1.class IS NOT NULL
RETURN m1.name, m2.name, m1.class, s.score
ORDER BY s.score DESC
LIMIT 10;

// Explore directory structure
MATCH (d:Directory)-[:CONTAINS]->(item)
WHERE d.path = 'src/main/java'
RETURN type(item) as item_type, 
       CASE WHEN item:File THEN item.path 
            WHEN item:Directory THEN item.path 
       END as name
LIMIT 20;
```

## Testing

Run the style checks and test suite:

```bash
flake8
pytest -q
```

## License

This project is licensed under the [MIT License](LICENSE).
