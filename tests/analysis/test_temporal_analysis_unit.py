#!/usr/bin/env python3

from __future__ import annotations

from typing import Any

from src.analysis.temporal_analysis import run_coupling, run_hotspots


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self._rows = rows or []

    def __iter__(self):
        yield from self._rows

    def single(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def data(self) -> list[dict[str, Any]]:
        return list(self._rows)

    @staticmethod
    def consume() -> None:  # for write queries that return summary
        return None


class _RecordingSession:
    def __init__(self, read_rows: list[dict[str, Any]] | None = None):
        self.queries: list[str] = []
        self.params: list[dict[str, Any]] = []
        self._read_rows = read_rows or []

    def run(self, query: str, params: dict[str, Any] | None = None):  # type: ignore[override]
        self.queries.append(" ".join(query.split()))
        self.params.append(params or {})
        # Return rows for read queries; write queries get an object with consume()
        if "RETURN" in query or "SHOW" in query:
            return _Result(self._read_rows)
        return _Result()

    # Add context manager protocol to match driver.session usage
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Driver:
    def __init__(self, session: _RecordingSession):
        self._session = session

    def session(self, database: str):  # noqa: D401
        return self._session


def test_run_coupling_write_path_runs_expected_queries() -> None:
    sess = _RecordingSession()
    drv = _Driver(sess)
    run_coupling(drv, database="neo4j", min_support=3, confidence_threshold=0.6, write=True)

    joined = "\n".join(sess.queries)
    # Expect APOC iterate, change count update, and confidence prune queries to be executed
    assert "CALL apoc.periodic.iterate" in joined
    assert "SET f.change_count" in joined
    assert "SET cc.confidence" in joined and "DELETE cc" in joined
    # Parameters recorded include thresholds
    merged_params = {}
    for p in sess.params:
        merged_params.update({k: v for k, v in p.items() if v is not None})
    assert merged_params.get("min_support") == 3
    assert merged_params.get("confidence_threshold") == 0.6


def test_run_coupling_read_path_uses_read_query_and_returns_rows() -> None:
    rows = [
        {"file1": "a.java", "file2": "b.java", "support": 5, "confidence": 0.75},
        {"file1": "c.java", "file2": "d.java", "support": 3, "confidence": 0.60},
    ]
    sess = _RecordingSession(read_rows=rows)
    drv = _Driver(sess)
    # Should not raise; queries captured
    run_coupling(drv, database="neo4j", min_support=2, confidence_threshold=0.5, write=False)
    assert any("MATCH (c:Commit)" in q for q in sess.queries)


def test_run_hotspots_read_and_write() -> None:
    read_rows = [
        {
            "path": "x.java",
            "recent_changes": 10,
            "method_count": 5,
            "total_lines": 1000,
            "score": 10 + 5 / 20.0 + 1.0,
        }
    ]
    sess = _RecordingSession(read_rows=read_rows)
    drv = _Driver(sess)
    # Read path
    run_hotspots(drv, database="neo4j", days=90, min_changes=2, top_n=10, write_back=False)
    assert any("RETURN f.path AS path" in q for q in sess.queries)
    # Write-back path
    run_hotspots(drv, database="neo4j", days=90, min_changes=2, top_n=10, write_back=True)
    assert any("SET f.recent_changes" in q for q in sess.queries)


def test_parse_args_temporal_coupling_flags():
    import sys

    from src.analysis.temporal_analysis import parse_args

    old = sys.argv
    try:
        sys.argv = [
            "prog",
            "coupling",
            "--min-support",
            "7",
            "--confidence-threshold",
            "0.6",
            "--create-relationships",
        ]
        args = parse_args()
        assert args.command == "coupling"
        assert args.min_support == 7
        assert abs(args.confidence_threshold - 0.6) < 1e-9
        assert args.create_relationships is True
    finally:
        sys.argv = old


def test_run_coupling_uses_write_or_read_query(monkeypatch):
    from src.analysis.temporal_analysis import run_coupling

    class _Ses:
        def __init__(self):
            self.calls = []

        class _R:
            def __init__(self, rows):
                self._rows = rows

            def __iter__(self):
                yield from self._rows

        def run(self, q, params):
            self.calls.append(" ".join(q.split()))
            # simulate returning a few rows
            return self._R(
                [
                    {"file1": "A.java", "file2": "B.java", "support": 10, "confidence": 0.8},
                ]
            )

        # context manager support
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Drv:
        def __init__(self):
            self.s = _Ses()

        def session(self, database: str):
            return self.s

    drv = _Drv()
    run_coupling(drv, database="neo4j", min_support=5, confidence_threshold=0.5, write=False)
    assert any("RETURN f1.path AS file1" in q for q in drv.s.calls)

    drv2 = _Drv()
    run_coupling(drv2, database="neo4j", min_support=5, confidence_threshold=0.5, write=True)
    assert any("MERGE (f1)-[cc:CO_CHANGED]->(f2)" in q for q in drv2.s.calls)


def _assert_dummy():
    # placeholder to avoid duplicate test name; real coverage above
    assert True
