#!/usr/bin/env python3

from __future__ import annotations

from types import SimpleNamespace


def _fake_gds_for_pagerank(write_back: bool):
    calls = {"pageRank.write": [], "pageRank.stream": [], "graph.project": []}

    class _GraphObj:
        def name(self):
            return "method_call_graph"

    class _Graph:
        @staticmethod
        def drop(name):
            return None

        @staticmethod
        def project(name, nodes, rels):
            calls["graph.project"].append((name, nodes, rels))
            return _GraphObj(), {"nodeCount": 3, "relationshipCount": 2}

    class _PageRank:
        @staticmethod
        def write(graph, **kwargs):
            calls["pageRank.write"].append(kwargs)
            # Return dict-like for logging access pattern
            return {"centralityDistribution": {"min": 0.1, "max": 0.9}}

        @staticmethod
        def stream(graph, **kwargs):
            calls["pageRank.stream"].append(kwargs)
            import pandas as pd

            return pd.DataFrame([[1, 0.9], [2, 0.8]], columns=["nodeId", "score"])

    def _run_cypher(q, params=None):
        import pandas as pd

        qn = " ".join(q.split())
        if "WHERE m.pagerank_score IS NOT NULL" in qn:
            # Top results after write_back
            return pd.DataFrame(
                [["A", "Cls", "F.java", 0.9]],
                columns=["method_name", "class_name", "file", "score"],
            )
        if "UNWIND $nodeIds as nodeId" in qn:
            return pd.DataFrame(
                [[1, "a", "C", "F.java"], [2, "b", "C", "F.java"]],
                columns=["nodeId", "method_name", "class_name", "file"],
            )
        return pd.DataFrame([[1]], columns=["ok"])  # default

    gds = SimpleNamespace(graph=_Graph(), pageRank=_PageRank(), run_cypher=_run_cypher)
    return gds, calls


def test_create_call_graph_projection_uses_natural_orientation():
    from src.analysis.centrality import create_call_graph_projection

    gds, calls = _fake_gds_for_pagerank(write_back=True)
    _ = create_call_graph_projection(gds)
    assert calls["graph.project"], "graph.project should be called"
    _name, nodes, rels = calls["graph.project"][0]
    assert nodes == ["Method"]
    assert isinstance(rels, dict) and "CALLS" in rels
    assert rels["CALLS"].get("orientation") == "NATURAL"


def test_run_pagerank_analysis_respects_constants_write_and_stream_paths():
    from src.analysis.centrality import run_pagerank_analysis
    from src.constants import PAGERANK_ALPHA, PAGERANK_ANALYSIS_ITERATIONS

    # Write-back path
    gds_w, calls_w = _fake_gds_for_pagerank(write_back=True)
    graph = object()  # not used by fake beyond identity
    res_w = run_pagerank_analysis(gds_w, graph, top_n=10, write_back=True)
    assert not res_w.empty
    assert calls_w["pageRank.write"], "pageRank.write should be called"
    kw = calls_w["pageRank.write"][0]
    assert kw["maxIterations"] == PAGERANK_ANALYSIS_ITERATIONS
    assert kw["dampingFactor"] == PAGERANK_ALPHA

    # Stream path
    gds_s, calls_s = _fake_gds_for_pagerank(write_back=False)
    res_s = run_pagerank_analysis(gds_s, graph, top_n=2, write_back=False)
    assert not res_s.empty and set(["nodeId", "method_name", "class_name", "file"]).issubset(
        res_s.columns
    )
    kw2 = calls_s["pageRank.stream"][0]
    assert kw2["maxIterations"] == PAGERANK_ANALYSIS_ITERATIONS
    assert kw2["dampingFactor"] == PAGERANK_ALPHA
