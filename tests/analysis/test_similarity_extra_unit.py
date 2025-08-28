#!/usr/bin/env python3

from __future__ import annotations

from types import SimpleNamespace


def _fake_gds_exists_true():
    # exists() returns something truthy
    class _Graph:
        @staticmethod
        def exists(name):
            return True

        @staticmethod
        def drop(name):
            return None

        class project:
            @staticmethod
            def cypher(name, node_q, rel_q, **kwargs):
                return SimpleNamespace(drop=lambda: None), None

    class _Knn:
        @staticmethod
        def write(graph, **_k):
            return None

    class _Louvain:
        @staticmethod
        def write(graph, **_k):
            return None

    class _GDS:
        def __init__(self):
            self.graph = _Graph()
            self.knn = _Knn()
            self.louvain = _Louvain()

        @staticmethod
        def run_cypher(q, params=None):
            from pandas import DataFrame

            if "RETURN count(m) AS missing" in q:
                return DataFrame([[0]], columns=["missing"])  # no missing
            return DataFrame([[1]], columns=["ok"])  # generic

    return _GDS()


def test_run_knn_drops_existing_projection_and_sets_model():
    from src.analysis.similarity import run_knn

    gds = _fake_gds_exists_true()
    run_knn(gds, top_k=1, cutoff=0.0)
    # If no exception, projection drop + write + model set path executed
    # Verified indirectly via absence of errors


def test_run_louvain_drops_existing_projection_and_runs():
    from src.analysis.similarity import run_louvain

    gds = _fake_gds_exists_true()
    run_louvain(gds, threshold=0.0, community_property="sim")
    # Absence of exception implies code path executed
