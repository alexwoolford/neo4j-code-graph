#!/usr/bin/env python3

from __future__ import annotations

import re
from pathlib import Path


def test_no_hardcoded_embedding_property_literals():
    """Ensure no code hardcodes the method embedding property name.

    Allowed:
      - The canonical definition in src/constants.py
      - Dynamic references using the EMBEDDING_PROPERTY constant
    Forbidden:
      - String literals like "embedding_unixcoder" in source files outside constants.py
    """
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = repo_root / "src"

    # Match string literals like "embedding_unixcoder" but allow the key "embedding_type"
    pattern = re.compile(r"[\'\"]embedding_(?!type[\'\"])^[^\'\"]+[\'\"]")

    offending: list[tuple[str, int, str]] = []
    for py in src_dir.rglob("*.py"):
        # Skip the definition file where the constant is constructed
        if py.name == "constants.py":
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except Exception:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offending.append((str(py.relative_to(repo_root)), idx, line.strip()))

    assert not offending, (
        "Hardcoded embedding property found; use src.constants.EMBEDDING_PROPERTY instead:\n"
        + "\n".join(f"{path}:{ln} => {snippet}" for path, ln, snippet in offending)
    )
