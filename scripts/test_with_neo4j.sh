#!/usr/bin/env bash
set -euo pipefail

# Config
NAME="neo4j-test"
IMAGE="neo4j:5.26"
AUTH="neo4j/test"
URI="bolt://localhost:7687"

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
if [ -n "${PYTEST_ARGS:-}" ]; then
  echo "pytest ${PYTEST_ARGS}"
  pytest ${PYTEST_ARGS}
else
  pytest -q
fi
