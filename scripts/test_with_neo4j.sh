#!/usr/bin/env bash
set -euo pipefail

# Config
NAME="neo4j-test"
IMAGE="neo4j:5.26"
AUTH="neo4j/test"
URI="bolt://127.0.0.1:7687"

echo "Starting Neo4j test container..."
docker run -d --rm \
  --name "$NAME" \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH="$AUTH" \
  -e NEO4J_PLUGINS='["apoc","graph-data-science"]' \
  -e NEO4J_dbms_security_procedures_unrestricted='apoc.*' \
  "$IMAGE" >/dev/null

cleanup() {
  echo "Stopping container..."
  docker stop "$NAME" >/dev/null || true
}
trap cleanup EXIT

echo "Waiting for Bolt to be available at $URI..."
for i in {1..90}; do
  if docker exec "$NAME" cypher-shell -u neo4j -p test "RETURN 1" >/dev/null 2>&1; then
    echo "Neo4j is ready."
    break
  fi
  sleep 2
done

export NEO4J_URI="$URI"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="test"
export NEO4J_DATABASE="neo4j"

echo "Running tests..."
# Sanity check connectivity from Python first
python - <<'PY'
from src.utils.common import create_neo4j_driver, get_neo4j_config
uri, user, pwd, db = get_neo4j_config()
with create_neo4j_driver(uri, user, pwd) as d:
    with d.session(database=db) as s:
        assert s.run("RETURN 1 as x").single()["x"] == 1
print("Connectivity OK:", uri)
PY
if [ -n "${PYTEST_ARGS:-}" ]; then
  echo "pytest ${PYTEST_ARGS}"
  pytest ${PYTEST_ARGS}
else
  pytest -q
fi
