#!/usr/bin/env python3

from types import SimpleNamespace


def _fake_gds():
    # Minimal fake Graph Data Science client with counters for calls
    calls = {"run_cypher": [], "exists": [], "project": []}

    class _Graph:
        def __init__(self):
            self._exists = False

        def exists(self, name):
            calls["exists"].append(name)
            return {"exists": self._exists}

        def drop(self, *_a, **_k):
            self._exists = False

        class project:
            @staticmethod
            def cypher(name, node_q, rel_q, **kwargs):
                calls["project"].append((name, node_q, rel_q, kwargs))
                return SimpleNamespace(drop=lambda: None), None

    class _Knn:
        @staticmethod
        def write(graph, **_k):
            return None

    class _Louvain:
        @staticmethod
        def write(graph, **_k):
            return None

    def _run_cypher(q, params=None):
        calls["run_cypher"].append((q, params))
        if "RETURN count(m)" in q:
            import pandas as pd  # type: ignore

            return pd.DataFrame([[0]], columns=["missing"])  # no missing embeddings
        return None

    gds = SimpleNamespace(run_cypher=_run_cypher, graph=_Graph(), knn=_Knn(), louvain=_Louvain())
    return gds, calls


def test_create_index_writes_expected_cypher(monkeypatch):
    from src.analysis.similarity import create_index

    gds, calls = _fake_gds()
    create_index(gds)
    # Should create index and await
    assert any("CREATE VECTOR INDEX" in q.upper() for (q, _p) in calls["run_cypher"])  # type: ignore[index]
    assert any("CALL DB.AWAITINDEX" in q.upper() for (q, _p) in calls["run_cypher"])  # type: ignore[index]


def test_run_knn_projects_embedding_property_and_sets_model():
    from src.analysis.similarity import run_knn

    gds, calls = _fake_gds()
    run_knn(gds, top_k=3, cutoff=0.5)
    # Verify projection query contains the embedding property alias
    assert any(
        "RETURN id(m) AS id" in node_q and "AS embedding" in node_q
        for (_n, node_q, _r, _k) in calls["project"]
    )  # type: ignore[index]
    # Should set model on relationships
    assert any("SET s.model" in q for (q, _p) in calls["run_cypher"])  # type: ignore[index]


def test_run_louvain_projects_threshold_and_property():
    from src.analysis.similarity import run_louvain

    gds, calls = _fake_gds()
    run_louvain(gds, threshold=0.7, community_property="simCommunity")
    # Relationship projection should pass threshold parameter
    assert any(
        "WHERE s.score >= $threshold" in rel_q for (_n, _node_q, rel_q, kwargs) in calls["project"]
    )  # type: ignore[index]
