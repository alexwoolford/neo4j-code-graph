#!/usr/bin/env bash
set -euo pipefail
set -x

# Config
NAME="neo4j-test"
IMAGE="neo4j:5.26-enterprise"
# Use 8+ char password to satisfy Neo4j policy
AUTH="neo4j/testtest"
URI="bolt://127.0.0.1:7687"

echo "Starting Neo4j test container..."
docker run -d --rm \
  --name "$NAME" \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH="$AUTH" \
  -e NEO4J_PLUGINS='["apoc","graph-data-science"]' \
  -e NEO4J_ACCEPT_LICENSE_AGREEMENT='yes' \
  -e NEO4J_dbms_security_procedures_unrestricted='apoc.*,gds.*' \
  -e NEO4J_dbms_security_procedures_allowlist='apoc.*,gds.*' \
  -e NEO4J_dbms_memory_heap_initial__size=512m \
  -e NEO4J_dbms_memory_heap_max__size=1g \
  -e NEO4J_dbms_memory_pagecache_size=256m \
  "$IMAGE" >/dev/null

cleanup() {
  echo "Stopping container..."
  docker stop "$NAME" >/dev/null || true
}
trap cleanup EXIT

echo "Waiting for Bolt to be available at $URI..."
ready=0
for i in {1..120}; do
  if docker exec "$NAME" cypher-shell -u neo4j -p testtest "RETURN 1" >/dev/null 2>&1; then
    echo "Neo4j is ready."
    ready=1
    break
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "Neo4j did not become ready in time. Showing last logs:"
  docker logs --tail=200 "$NAME" || true
  echo "Checking container status:" && docker ps -a | grep "$NAME" || true
  exit 1
fi

export NEO4J_URI="$URI"
export NEO4J_USERNAME="neo4j"
export NEO4J_PASSWORD="testtest"
export NEO4J_DATABASE="neo4j"

# Ensure plugins (GDS/APOC) are fully loaded before running tests
echo "Waiting for GDS and APOC procedures to be available..."
plugins_ready=0
for i in {1..240}; do
  if docker exec "$NAME" cypher-shell -u neo4j -p testtest "CALL gds.version()" >/dev/null 2>&1 \
     && docker exec "$NAME" cypher-shell -u neo4j -p testtest "RETURN apoc.version() AS v" >/dev/null 2>&1; then
    echo "GDS and APOC are available."
    plugins_ready=1
    break
  fi
  if (( i % 30 == 0 )); then
    echo "Still waiting for plugins... ($i)"
    docker exec "$NAME" cypher-shell -u neo4j -p testtest "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'gds.' OR name STARTS WITH 'apoc.' RETURN count(*) AS c" || true
  fi
  sleep 2
done
if [ "$plugins_ready" -ne 1 ]; then
  echo "GDS/APOC did not become available in time. Showing last logs:"
  docker logs --tail=200 "$NAME" || true
  exit 1
fi

echo "Running tests..."
# Extra diagnostics to help CI when failures occur
docker exec "$NAME" cypher-shell -u neo4j -p testtest "SHOW DATABASES" || true
# Sanity check connectivity from Python first
PYTHONPATH="$(cd "$(dirname "$0")/.." && pwd)":"$PYTHONPATH" python - <<'PY'
from src.utils.common import create_neo4j_driver, get_neo4j_config
uri, user, pwd, db = get_neo4j_config()
with create_neo4j_driver(uri, user, pwd) as d:
    with d.session(database=db) as s:
        assert s.run("RETURN 1 as x").single()["x"] == 1
print("Connectivity OK:", uri)
PY
if [ -n "${PYTEST_ARGS:-}" ]; then
  echo "pytest ${PYTEST_ARGS}"
  set +e
  pytest ${PYTEST_ARGS}
  status=$?
  set -e
else
  # By default, run only live tests against the running Neo4j instance
  set +e
  pytest -q -m live
  status=$?
  set -e
fi

if [ "$status" -ne 0 ]; then
  echo "Tests failed with status $status. Dumping recent container logs and procedure availability..."
  docker logs --tail=300 "$NAME" || true
  docker exec "$NAME" cypher-shell -u neo4j -p testtest "CALL dbms.components() YIELD name, versions RETURN name, versions" || true
  docker exec "$NAME" cypher-shell -u neo4j -p testtest "CALL gds.version()" || true
  docker exec "$NAME" cypher-shell -u neo4j -p testtest "RETURN apoc.version() AS v" || true
  exit "$status"
fi
