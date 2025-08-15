#!/usr/bin/env python3
"""
Wait for a Neo4j instance to become ready.

Reads configuration from environment variables:
  - NEO4J_URI (e.g., bolt://127.0.0.1:7687)
  - NEO4J_USERNAME
  - NEO4J_PASSWORD
  - NEO4J_DATABASE (optional)
  - NEO4J_WAIT_TIMEOUT_SECONDS (optional, default: 420)

Exit code 0 on success; non-zero on timeout/failure.
"""

from __future__ import annotations

import os
import sys
import time

from neo4j import GraphDatabase


def wait_for_neo4j(
    uri: str,
    username: str,
    password: str,
    database: str | None = None,
    timeout_seconds: int = 420,
) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with GraphDatabase.driver(uri, auth=(username, password)) as driver:
                session_kwargs = {"database": database} if database else {}
                with driver.session(**session_kwargs) as session:
                    session.run("RETURN 1").consume()
            print("Neo4j is ready")
            return
        except Exception as exc:  # noqa: BLE001 - bubble up only after timeout
            last_error = exc
            time.sleep(2)
    raise SystemExit(f"Neo4j not ready before timeout: {last_error}")


def main() -> None:
    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    database = os.environ.get("NEO4J_DATABASE")
    timeout_str = os.environ.get("NEO4J_WAIT_TIMEOUT_SECONDS", "420")
    if not (uri and username and password):
        print("NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set", file=sys.stderr)
        raise SystemExit(2)
    try:
        timeout = int(timeout_str)
    except ValueError:
        timeout = 420
    wait_for_neo4j(uri, username, password, database=database, timeout_seconds=timeout)


if __name__ == "__main__":
    main()
