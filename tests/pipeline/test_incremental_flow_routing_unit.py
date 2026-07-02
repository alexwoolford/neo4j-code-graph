"""Fast unit tests for WP4 incremental orchestration wiring in code_graph_flow.

These verify routing (incremental vs full), that provenance is recorded around
both paths, and that a failure records status='failed' — without touching Neo4j
(all task/provenance/decision helpers are monkeypatched).
"""

from __future__ import annotations

import contextlib

import pytest


def _stub_common(monkeypatch, pf, run_calls, finishes):
    monkeypatch.setattr(pf, "setup_schema_task", lambda *a, **k: run_calls.append("schema"))
    monkeypatch.setattr(pf, "get_head_sha", lambda p: "headsha")
    monkeypatch.setattr(pf, "_resolve_branch", lambda p: "main")
    monkeypatch.setattr(pf, "normalize_repo_url", lambda u: "url")
    monkeypatch.setattr(pf, "_record_start_safe", lambda *a, **k: "iid")
    monkeypatch.setattr(pf, "_record_finish_safe", lambda *a, **k: finishes.append(a[-1]))

    @contextlib.contextmanager
    def _fake_session(*_a, **_k):
        yield object()

    monkeypatch.setattr(pf, "_provenance_session", _fake_session)


def test_incremental_routes_to_incremental_and_records_success(monkeypatch, tmp_path):
    from src.pipeline import prefect_flow as pf

    repo = tmp_path / "repo"
    repo.mkdir()
    run_calls: list[str] = []
    finishes: list[str] = []
    _stub_common(monkeypatch, pf, run_calls, finishes)

    monkeypatch.setattr(
        pf,
        "get_last_successful_ingest",
        lambda s, u, b: {"head_sha": "basesha", "schema_version": 1, "branch": "main"},
    )
    monkeypatch.setattr(pf, "decide_ingest_mode", lambda *a, **k: ("incremental", "delta"))

    ran: dict[str, tuple] = {}
    monkeypatch.setattr(pf, "_run_incremental", lambda *a, **k: ran.__setitem__("incr", a))
    monkeypatch.setattr(pf, "_run_full", lambda *a, **k: ran.__setitem__("full", a))

    pf.code_graph_flow(repo_url=str(repo), incremental=True)

    assert "incr" in ran and "full" not in ran
    # since_sha (2nd positional arg of _run_incremental) threaded from the HWM.
    assert ran["incr"][1] == "basesha"
    assert finishes == ["success"]


def test_incremental_without_hwm_falls_back_to_full(monkeypatch, tmp_path):
    from src.pipeline import prefect_flow as pf

    repo = tmp_path / "repo"
    repo.mkdir()
    run_calls: list[str] = []
    finishes: list[str] = []
    _stub_common(monkeypatch, pf, run_calls, finishes)

    monkeypatch.setattr(pf, "get_last_successful_ingest", lambda s, u, b: None)
    monkeypatch.setattr(pf, "decide_ingest_mode", lambda *a, **k: ("full", "no high-water mark"))

    ran: dict[str, tuple] = {}
    monkeypatch.setattr(pf, "_run_incremental", lambda *a, **k: ran.__setitem__("incr", a))
    monkeypatch.setattr(pf, "_run_full", lambda *a, **k: ran.__setitem__("full", a))

    pf.code_graph_flow(repo_url=str(repo), incremental=True)

    assert "full" in ran and "incr" not in ran
    assert finishes == ["success"]


def test_default_flow_is_full_and_records_success(monkeypatch, tmp_path):
    from src.pipeline import prefect_flow as pf

    repo = tmp_path / "repo"
    repo.mkdir()
    run_calls: list[str] = []
    finishes: list[str] = []
    _stub_common(monkeypatch, pf, run_calls, finishes)

    ran: dict[str, tuple] = {}
    monkeypatch.setattr(pf, "_run_full", lambda *a, **k: ran.__setitem__("full", a))
    # decide_ingest_mode must NOT be consulted when incremental is not requested.
    monkeypatch.setattr(
        pf,
        "decide_ingest_mode",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    pf.code_graph_flow(repo_url=str(repo), incremental=False)

    assert "full" in ran
    assert finishes == ["success"]


def test_failure_records_failed_status(monkeypatch, tmp_path):
    from src.pipeline import prefect_flow as pf

    repo = tmp_path / "repo"
    repo.mkdir()
    run_calls: list[str] = []
    finishes: list[str] = []
    _stub_common(monkeypatch, pf, run_calls, finishes)

    def _boom(*_a, **_k):
        raise RuntimeError("write failed")

    monkeypatch.setattr(pf, "_run_full", _boom)

    with pytest.raises(Exception):
        pf.code_graph_flow(repo_url=str(repo), incremental=False)

    assert finishes == ["failed"]
