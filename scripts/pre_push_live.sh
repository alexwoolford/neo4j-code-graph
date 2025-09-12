#!/usr/bin/env bash
set -euo pipefail

echo "[pre-push] Running pre-commit checks..."
pre-commit run --all-files

echo "[pre-push] Verifying Docker/Testcontainers availability..."
if [[ ! -S /var/run/docker.sock && -z "${DOCKER_HOST:-}" ]]; then
  echo "[pre-push] Docker is not available. Live tests require Docker (Testcontainers)." >&2
  exit 2
fi

echo "[pre-push] Running live tests (fail fast on first failure)..."
pytest -q -m live --maxfail=1

echo "[pre-push] Live tests passed. Safe to push."
