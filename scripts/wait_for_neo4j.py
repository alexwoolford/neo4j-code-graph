#!/usr/bin/env python3
"""
Wait for a Neo4j instance to become ready.

You can pass connection settings via CLI flags or rely on .env/env defaults:
  --uri, --username, --password, --database (optional)
  --timeout-seconds (optional, default: 420)

Exit code 0 on success; non-zero on timeout/failure.
"""

from __future__ import annotations

import argparse
import sys as _sys
import time
from pathlib import Path as _Path

# Ensure both repo and installed contexts can import modules consistently
_repo_root = _Path(__file__).resolve().parents[1]
_src_dir = _repo_root / "src"
for _p in (str(_repo_root), str(_src_dir)):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from neo4j import GraphDatabase

try:
    from src.utils.common import add_common_args, resolve_neo4j_args
except Exception:  # pragma: no cover - repo-local fallback
    from utils.common import add_common_args, resolve_neo4j_args  # type: ignore


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
                if database:
                    with driver.session(database=database) as session:
                        session.run("RETURN 1").consume()
                else:
                    with driver.session() as session:
                        session.run("RETURN 1").consume()
            print("Neo4j is ready")
            return
        except Exception as exc:  # noqa: BLE001 - bubble up only after timeout
            last_error = exc
            time.sleep(2)
    raise SystemExit(f"Neo4j not ready before timeout: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait for Neo4j to become ready")
    add_common_args(parser)
    parser.add_argument(
        "--timeout-seconds", type=int, default=420, help="Timeout in seconds (default: 420)"
    )
    args = parser.parse_args()

    uri, user, pwd, db = resolve_neo4j_args(args.uri, args.username, args.password, args.database)
    wait_for_neo4j(uri, user, pwd, database=db, timeout_seconds=int(args.timeout_seconds))


if __name__ == "__main__":
    main()
