#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def run_in_batches(
    session: Any,
    query: str,
    records: Iterable[Any],
    batch_size: int,
    param_key: str,
) -> None:
    """Execute a Cypher query over records in batches using UNWIND.

    Args:
        session: Active Neo4j session
        query: Cypher statement using UNWIND $param_key AS ...
        records: Iterable of records to be passed to Cypher
        batch_size: Number of items per batch
        param_key: Name of the Cypher parameter holding the batch
    """
    # Convert to list once to allow slicing and length introspection
    items = list(records)
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        if not batch:
            continue
        session.run(query, **{param_key: batch})


def get_database_batch_size(
    has_embeddings: bool = False, estimated_size_mb: int | None = None
) -> int:
    """Choose an appropriate batch size for Neo4j writes.

    - Smaller batches when embeddings are present or data is large
    - Larger batches for simple operations
    """
    if has_embeddings:
        # Embeddings payloads are large; prefer smaller batches to avoid memory pressure
        return 250
    if estimated_size_mb and estimated_size_mb > 1:
        return 500
    return 1000
