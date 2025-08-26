#!/usr/bin/env python3
"""
Validate Cypher snippets by running EXPLAIN on each tagged block in .cyp files.

Usage:
  python scripts/validate_cypher_snippets.py <queries_dir> [--uri ... --username ... --password ... --database ...]

Environment:
  If CLI args are not provided, connection defaults come from .env via get_neo4j_config()

Notes:
  - Uses EXPLAIN, so no data is required and nothing is written.
  - Fails fast on the first invalid query.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from pathlib import Path

from neo4j import GraphDatabase

try:
    from src.utils.common import add_common_args, resolve_neo4j_args
except Exception:  # pragma: no cover - repo-local fallback
    from utils.common import add_common_args, resolve_neo4j_args  # type: ignore

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
        if database:
            with driver.session(database=database) as session:
                for _file_path, _tag, query in queries:
                    session.run(f"EXPLAIN\n{query}")  # type: ignore[arg-type]
                    num_validated += 1
        else:
            with driver.session() as session:
                for _file_path, _tag, query in queries:
                    session.run(f"EXPLAIN\n{query}")  # type: ignore[arg-type]
                    num_validated += 1
    print(f"Validated {num_validated} Cypher snippets via EXPLAIN")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Cypher snippets (EXPLAIN) from .cyp files in a directory"
    )
    parser.add_argument("queries_dir", help="Directory containing .cyp files with tagged snippets")
    add_common_args(parser)
    args = parser.parse_args()

    root = Path(args.queries_dir).resolve()
    if not root.exists():
        raise SystemExit(f"Directory not found: {root}")

    uri, user, pwd, db = resolve_neo4j_args(args.uri, args.username, args.password, args.database)
    validate_queries(uri, user, pwd, iter_queries(root), database=db)


if __name__ == "__main__":
    main()
