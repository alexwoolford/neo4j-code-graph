# Scripts

Helper scripts used in CI, local development, and docs.

- create_database.py: Create a Neo4j database by name using current connection settings. Useful on multi-DB instances when provisioning a fresh database. Reads config from environment/.env via `src/utils/neo4j_utils.get_neo4j_config()`.

- wait_for_neo4j.py: Block until a Neo4j instance is ready to accept queries. Reads `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, optional `NEO4J_DATABASE`, and `NEO4J_WAIT_TIMEOUT_SECONDS` (default 420). Exits non-zero on timeout.

- validate_cypher_snippets.py: Parse `.cyp` files under a directory for tagged query blocks and run `EXPLAIN` against a Neo4j instance to validate syntax. Used by docs CI to prevent broken queries in documentation.

- generate_prefect_dag.py: Produce a DAG image for the Prefect flow (`src/pipeline/prefect_flow.py`). Attempts Prefect’s native visualize API, falling back to a static Graphviz render. Output is written to `docs/modules/ROOT/assets/images/prefect-dag.png`.

Notes
- All scripts use context managers with the Neo4j driver to avoid deprecation warnings.
- No secrets are hardcoded; configuration is taken from `.env`/environment. CLI args override env where applicable.
