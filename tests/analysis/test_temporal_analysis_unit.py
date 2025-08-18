#!/usr/bin/env python3

from __future__ import annotations


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


def test_run_hotspots_read_and_write(monkeypatch):
    from src.analysis.temporal_analysis import run_hotspots

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
            return self._R(
                [
                    {
                        "path": "A.java",
                        "recent_changes": 5,
                        "method_count": 3,
                        "total_lines": 200,
                        "score": 1.5,
                    },
                ]
            )

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
    run_hotspots(drv, database="neo4j", days=90, min_changes=2, top_n=10, write_back=False)
    assert any("RETURN f.path AS path" in q for q in drv.s.calls)

    drv2 = _Drv()
    run_hotspots(drv2, database="neo4j", days=90, min_changes=2, top_n=10, write_back=True)
    assert any("SET f.recent_changes =" in q for q in drv2.s.calls)
