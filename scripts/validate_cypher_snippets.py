#!/usr/bin/env python3
"""
Validate Cypher snippets by running EXPLAIN on each tagged block in .cyp files.

Usage:
  python scripts/validate_cypher_snippets.py docs/modules/ROOT/examples/queries

Environment:
  NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD (required)

Notes:
  - Uses EXPLAIN, so no data is required and nothing is written.
  - Fails fast on the first invalid query.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from neo4j import GraphDatabase

TAG_START_RE = re.compile(r"^\s*//\s*tag::([\w:-]+)\[\]\s*$")
TAG_END_RE = re.compile(r"^\s*//\s*end::([\w:-]+)\[\]\s*$")


def extract_tagged_queries(file_path: Path) -> dict[str, str]:
    tagged: dict[str, str] = {}
    current_tag: str | None = None
    buffer: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        start = TAG_START_RE.match(line)
        end = TAG_END_RE.match(line)
        if start:
            if current_tag is not None:
                raise ValueError(f"Nested tag not allowed in {file_path}")
            current_tag = start.group(1)
            buffer = []
            continue
        if end:
            if current_tag is None or end.group(1) != current_tag:
                raise ValueError(
                    f"Mismatched tag end {end.group(1)} in {file_path}; open={current_tag}"
                )
            tagged[current_tag] = "\n".join(buffer).strip()
            current_tag = None
            buffer = []
            continue
        if current_tag is not None:
            buffer.append(line)
    return tagged


def iter_queries(root: Path) -> Iterable[tuple[Path, str, str]]:
    for file_path in sorted(root.rglob("*.cyp")):
        tags = extract_tagged_queries(file_path)
        for tag, query in tags.items():
            if not query:
                raise ValueError(f"Empty query for tag '{tag}' in {file_path}")
            yield file_path, tag, query


def validate_queries(
    uri: str,
    user: str,
    pwd: str,
    queries: Iterable[tuple[Path, str, str]],
    database: str | None = None,
) -> None:
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        num_validated = 0
        session_kwargs = {"database": database} if database else {}
        with driver.session(**session_kwargs) as session:
            for file_path, tag, query in queries:
                session.run(f"EXPLAIN\n{query}")
                num_validated += 1
    print(f"Validated {num_validated} Cypher snippets via EXPLAIN")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/validate_cypher_snippets.py <queries_dir>")
        sys.exit(2)
    root = Path(sys.argv[1]).resolve()
    if not root.exists():
        raise SystemExit(f"Directory not found: {root}")

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    pwd = os.environ.get("NEO4J_PASSWORD")
    if not all([uri, user, pwd]):
        raise SystemExit("NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set")
    database = os.environ.get("NEO4J_DATABASE")

    validate_queries(uri, user, pwd, iter_queries(root), database=database)


if __name__ == "__main__":
    main()
