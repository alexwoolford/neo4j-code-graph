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
import sys
from collections.abc import Iterable
from pathlib import Path

from neo4j import GraphDatabase

# Ensure repository import paths are available when run from CI or scripts/
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_SRC_DIR = _REPO_ROOT / "src"
for _p in (_REPO_ROOT, _SRC_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from src.utils.common import add_common_args, resolve_neo4j_args
except Exception as err:  # pragma: no cover - fail fast rather than silent fallback
    raise SystemExit(
        "Failed to import project utilities. Ensure 'pip install -e .' or PYTHONPATH includes repo root."
    ) from err

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


def _split_cypher_statements(query: str) -> list[str]:
    """Split a string containing one or more Cypher statements into individual statements.

    Uses a simple state machine to ignore semicolons inside quoted strings or backticks.
    """
    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    in_backtick = False
    escape = False
    for ch in query:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double and not in_backtick:
            in_single = not in_single
            buf.append(ch)
            continue
        if ch == '"' and not in_single and not in_backtick:
            in_double = not in_double
            buf.append(ch)
            continue
        if ch == "`" and not in_single and not in_double:
            in_backtick = not in_backtick
            buf.append(ch)
            continue
        if ch == ";" and not in_single and not in_double and not in_backtick:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


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
            with driver.session(database=database) as session:  # type: ignore[reportUnknownMemberType]
                for file_path, tag, query in queries:
                    for stmt in _split_cypher_statements(query):
                        session.run(f"EXPLAIN\n{stmt}")  # type: ignore[arg-type]
                        num_validated += 1
        else:
            with driver.session() as session:  # type: ignore[reportUnknownMemberType]
                for file_path, tag, query in queries:
                    for stmt in _split_cypher_statements(query):
                        session.run(f"EXPLAIN\n{stmt}")  # type: ignore[arg-type]
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
