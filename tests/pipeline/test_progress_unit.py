#!/usr/bin/env python3

from __future__ import annotations


class _FakeResultIterable:
    def __init__(self, rows: list[dict[str, object]]):
        self._rows = rows

    def __iter__(self):
        yield from self._rows

    def single(self):
        # If used, return first row or a default empty row
        return self._rows[0] if self._rows else {}


class _FakeSession:
    def __init__(self, script: dict[str, object]):
        self._script = script

    def run(self, query: str, *args, **kwargs):  # noqa: D401
        q = " ".join(query.split())
        # Switch on key substrings
        if "CALL db.labels()" in q:
            return _FakeResultIterable(
                [
                    {"label": "File", "count": 3},
                    {"label": "Method", "count": 5},
                ]
            )
        if "CALL db.relationshipTypes()" in q:
            return _FakeResultIterable(
                [
                    {"relationshipType": "IMPORTS", "count": 2},
                    {"relationshipType": "CALLS", "count": 1},
                ]
            )
        if "MATCH (f:File) WHERE f.embedding IS NOT NULL" in q:
            return _FakeResultIterable([{"count": 1}])
        if "MATCH (m:Method) WHERE m.embedding IS NOT NULL" in q:
            return _FakeResultIterable([{"count": 0}])
        return _FakeResultIterable([])

    # Context manager API used by the code under test
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDriver:
    def __init__(self):
        self._session = _FakeSession({})

    def session(self, database: str):  # noqa: D401
        return self._session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_check_database_state_partial_statuses():
    from src.pipeline.progress import check_database_state

    fake_driver = _FakeDriver()
    state = check_database_state(fake_driver, database="neo4j")

    # Node/rel aggregation
    assert state["total_nodes"] == 8
    assert state["total_rels"] == 3
    assert state["node_types"]["File"] == 3
    assert state["rel_types"]["IMPORTS"] == 2

    # Status booleans from counts: 1/3 files embedded (partial), 0/5 methods embedded (not started)
    assert state["files_complete"] is False
    assert state["methods_complete"] is False
    assert state["imports_complete"] is True
    assert state["calls_partial"] is True
