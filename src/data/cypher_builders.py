#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Iterable


def iter_schema_constraint_cypher() -> Iterable[tuple[str, str]]:
    """Yield (name, cypher) pairs for managed constraints.

    Mirrors SCHEMA_CONSTRAINTS in schema_management to avoid duplication.
    """
    from src.data.schema_management import SCHEMA_CONSTRAINTS

    for name, _label, _props, cypher in SCHEMA_CONSTRAINTS:
        yield name, cypher


def iter_schema_index_cypher() -> Iterable[tuple[str, str]]:
    """Yield (name, cypher) pairs for managed indexes.

    Mirrors SCHEMA_INDEXES in schema_management to avoid duplication.
    """
    from src.data.schema_management import SCHEMA_INDEXES

    for name, _label, cypher in SCHEMA_INDEXES:
        yield name, cypher


__all__ = [
    "iter_schema_constraint_cypher",
    "iter_schema_index_cypher",
]
