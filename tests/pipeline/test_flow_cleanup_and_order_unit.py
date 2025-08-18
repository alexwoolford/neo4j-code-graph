#!/usr/bin/env python3

from __future__ import annotations


def test_flow_respects_cleanup_flag_and_calls_in_order(monkeypatch, tmp_path):
    from src.pipeline import prefect_flow as pf

    calls: list[str] = []

    def rec(name):
        def _fn(*_a, **_k):
            calls.append(name)
            return None

        return _fn

    # Patch tasks and helpers to record order; return simple values where needed
    monkeypatch.setattr(pf, "setup_schema_task", rec("setup_schema"))
    monkeypatch.setattr(pf, "cleanup_task", rec("cleanup"))
    monkeypatch.setattr(
        pf,
        "clone_repo_task",
        type(
            "T",
            (),
            {
                "submit": staticmethod(
                    lambda url: type("R", (), {"result": staticmethod(lambda: str(tmp_path))})()
                )
            },
        ),
    )
    monkeypatch.setattr(pf, "extract_code_task", rec("extract_code"))
    monkeypatch.setattr(pf, "embed_files_task", rec("embed_files"))
    monkeypatch.setattr(pf, "embed_methods_task", rec("embed_methods"))
    monkeypatch.setattr(pf, "write_graph_task", rec("write_graph"))
    monkeypatch.setattr(pf, "cleanup_artifacts_task", rec("cleanup_artifacts"))
    monkeypatch.setattr(pf, "git_history_task", rec("git_history"))
    monkeypatch.setattr(pf, "coupling_task", rec("coupling"))
    monkeypatch.setattr(
        pf, "similarity_task", type("T2", (), {"submit": staticmethod(lambda *a, **k: "sim_state")})
    )
    monkeypatch.setattr(
        pf, "louvain_task", type("T3", (), {"submit": staticmethod(lambda *a, **k: "louv_state")})
    )
    monkeypatch.setattr(
        pf,
        "centrality_task",
        type("T4", (), {"submit": staticmethod(lambda *a, **k: "cent_state")}),
    )
    monkeypatch.setattr(
        pf,
        "cve_task",
        type(
            "T5",
            (),
            {
                "submit": staticmethod(
                    lambda *a, **k: type("R", (), {"result": staticmethod(lambda: None)})()
                )
            },
        ),
    )

    # Run with cleanup disabled
    pf.code_graph_flow(repo_url="https://example.com/repo.git", cleanup=False)

    # Assertions: cleanup() is omitted and key stages appear in expected sequence
    assert "cleanup" not in calls
    expected_order = [
        "setup_schema",
        "extract_code",
        "embed_files",
        "embed_methods",
        "write_graph",
        "cleanup_artifacts",
        "git_history",
        "coupling",
    ]
    # Ensure the expected prefix order appears in the calls list
    indices = [calls.index(name) for name in expected_order]
    assert indices == sorted(indices)
