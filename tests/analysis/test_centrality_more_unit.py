#!/usr/bin/env python3

from __future__ import annotations

from types import SimpleNamespace


def _fake_gds_betweenness(write_back: bool):
    calls = {"betweenness.write": 0, "betweenness.stream": 0, "run_cypher": []}

    class _Betw:
        @staticmethod
        def write(graph, **kwargs):
            calls["betweenness.write"] += 1
            return {"ok": 1}

        @staticmethod
        def stream(graph, **kwargs):
            calls["betweenness.stream"] += 1
            import pandas as pd

            return pd.DataFrame([[1, 0.4], [2, 0.3]], columns=["nodeId", "score"])

    def _run_cypher(q, params=None):
        import pandas as pd

        calls["run_cypher"].append(" ".join(q.split()))
        if "UNWIND $nodeIds as nodeId" in q:
            return pd.DataFrame(
                [[1, "m1", "C", "F.java"], [2, "m2", "C", "F.java"]],
                columns=["nodeId", "method_name", "class_name", "file"],
            )
        if "WHERE m.betweenness_score IS NOT NULL" in q:
            return pd.DataFrame(
                [["m1", "C", "F.java", 0.4]],
                columns=["method_name", "class_name", "file", "score"],
            )
        return pd.DataFrame([[1]], columns=["ok"])  # default

    gds = SimpleNamespace(betweenness=_Betw(), run_cypher=_run_cypher)
    return gds, calls


def test_run_betweenness_analysis_stream_and_write_paths():
    from src.analysis.centrality import run_betweenness_analysis

    graph = object()
    # Stream path
    gds_s, calls_s = _fake_gds_betweenness(write_back=False)
    res_s = run_betweenness_analysis(gds_s, graph, top_n=2, write_back=False)
    assert not res_s.empty and {"method_name", "class_name", "file"}.issubset(res_s.columns)
    assert calls_s["betweenness.stream"] == 1

    # Write path
    gds_w, calls_w = _fake_gds_betweenness(write_back=True)
    res_w = run_betweenness_analysis(gds_w, graph, top_n=1, write_back=True)
    assert not res_w.empty and "score" in res_w.columns
    assert calls_w["betweenness.write"] == 1


def _fake_gds_degree(write_back: bool):
    calls = {"run_cypher": []}

    def _run_cypher(q, params=None):
        import pandas as pd

        qn = " ".join(q.split())
        calls["run_cypher"].append(qn)
        if qn.startswith("MATCH (m:Method) OPTIONAL MATCH (m)-[out:CALLS]->()"):
            return pd.DataFrame(
                [[1, "m1", "C", "F.java", 2, 1, 3]],
                columns=[
                    "nodeId",
                    "method_name",
                    "class_name",
                    "file",
                    "out_degree",
                    "in_degree",
                    "total_degree",
                ],
            )
        return pd.DataFrame([[1]], columns=["ok"])  # write-back path

    gds = SimpleNamespace(run_cypher=_run_cypher)
    return gds, calls


def test_run_degree_analysis_query_and_writeback():
    from src.analysis.centrality import run_degree_analysis

    gds, calls = _fake_gds_degree(write_back=False)
    res = run_degree_analysis(gds, graph=object(), top_n=1, write_back=False)
    assert not res.empty and {"total_degree", "in_degree", "out_degree"}.issubset(res.columns)

    # Write-back triggers second cypher with SET
    gds2, calls2 = _fake_gds_degree(write_back=True)
    _ = run_degree_analysis(gds2, graph=object(), top_n=1, write_back=True)
    assert any("SET m.out_degree" in q for q in calls2["run_cypher"])  # write update executed
