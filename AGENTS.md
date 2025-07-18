# AGENTS Instructions

- Install dependencies from `requirements.txt` and `dev-requirements.txt`.
- Run `flake8` and `pytest -q` before committing.
- Format Python code with `black`.
- Tests mock the database connection, so they pass without a running Neo4j
  instance. If you want to run the scripts against a real database, create a
  `.env` file from `.env.example` and supply your connection details.
