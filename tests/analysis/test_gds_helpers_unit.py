#!/usr/bin/env python3

from __future__ import annotations

from typing import Any

from src.analysis.gds_helpers import (
    create_method_calls_projection,
    create_similarity_projection,
    enrich_node_ids_with_method_details,
)


class _FakeGraphAPI:
    def __init__(self):
        self.dropped = []
        self.projected = []

    def drop(self, name: str) -> None:  # type: ignore[no-untyped-def]
        self.dropped.append(name)
        # emulate drop success

    def project(self, name: str, nodes: list[str], rels: dict[str, Any]):  # type: ignore[no-untyped-def]
        self.projected.append((name, nodes, rels))
        return (object(), {"name": name})

    class project_cypher:
        @staticmethod
        def __call__(*args, **kwargs):  # pragma: no cover - placeholder
            raise NotImplementedError


class _FakeGDS:
    def __init__(self):
        self.graph = _FakeGraphAPI()
        self.calls = []

    def run_cypher(self, query: str, params: dict[str, Any]):  # type: ignore[no-untyped-def]
        self.calls.append((query, params))
        # Return a pandas-like object; for the test we just return the params
        return {"params": params}

    class graph:
        project = None
        drop = None
        project_cypher = None


def test_create_method_calls_projection():
    gds = _FakeGDS()
    # Patch graph API methods to instance
    gds.graph = _FakeGraphAPI()
    G, meta = create_method_calls_projection(gds, graph_name="mcg")
    assert meta["name"] == "mcg"
    assert gds.graph.projected and gds.graph.projected[0][0] == "mcg"


def test_enrich_node_ids_with_method_details_empty_returns_frame():
    gds = _FakeGDS()
    # Empty node list returns empty DataFrame-like object
    out = enrich_node_ids_with_method_details(gds, [])
    assert getattr(out, "empty", True) or getattr(out, "shape", (0, 0))[0] == 0


def test_enrich_node_ids_with_method_details_runs_cypher():
    gds = _FakeGDS()
    # Minimal behavior: returns dict with params as we implemented above
    out = enrich_node_ids_with_method_details(gds, [1, 2, 3])
    assert out["params"]["nodeIds"] == [1, 2, 3]


def test_create_similarity_projection_calls_project_cypher():
    class FakeProject:
        def cypher(self, name: str, node_q: str, rel_q: str, parameters: dict[str, Any]):
            # store on local variable to avoid IDE warning about defining attrs outside __init__
            args = (name, node_q, rel_q, parameters)
            self._args = args
            return (object(), {"name": name, "params": parameters})

    class GDSWithCypher:
        def __init__(self):
            self.graph = type("G", (), {})()
            self.graph.drop = lambda name: None
            self.graph.project = FakeProject()

    gds = GDSWithCypher()
    _, meta = create_similarity_projection(gds, threshold=0.9, graph_name="simG")
    assert meta["name"] == "simG"
    assert meta["params"]["threshold"] == 0.9
