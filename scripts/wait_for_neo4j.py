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
import os
import time

from neo4j import GraphDatabase

try:
    # Preferred: use project helpers when the package is installed
    from src.utils.common import add_common_args, resolve_neo4j_args  # type: ignore
except Exception:  # pragma: no cover - standalone fallback without import hacks
    # Minimal, non-hacky fallbacks so this script can run before the package is installed.
    # Matches CLI semantics of the project without sys.path manipulation.
    def add_common_args(parser: argparse.ArgumentParser) -> None:  # type: ignore[no-redef]
        parser.add_argument("--uri", default=os.getenv("NEO4J_URI"))
        parser.add_argument("--username", default=os.getenv("NEO4J_USERNAME"))
        parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
        parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE"))

    def _ensure_port(uri: str) -> str:
        # Append default bolt port if none present
        if ":" not in uri.split("//", 1)[-1]:
            if uri.startswith("neo4j://") or uri.startswith("bolt://"):
                return uri + ":7687"
        return uri

    def resolve_neo4j_args(  # type: ignore[no-redef]
        explicit_uri: str | None,
        explicit_username: str | None,
        explicit_password: str | None,
        explicit_database: str | None,
    ) -> tuple[str, str, str, str]:
        uri = explicit_uri or os.getenv("NEO4J_URI", "")
        user = explicit_username or os.getenv("NEO4J_USERNAME", "")
        pwd = explicit_password or os.getenv("NEO4J_PASSWORD", "")
        db = explicit_database or os.getenv("NEO4J_DATABASE", "")
        if not uri or not user or not pwd:
            raise SystemExit(
                "Missing required Neo4j settings. Provide --uri/--username/--password or set NEO4J_* env vars."
            )
        return _ensure_port(uri), user, pwd, db or "neo4j"


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
