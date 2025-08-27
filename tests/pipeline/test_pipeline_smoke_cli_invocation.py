from __future__ import annotations


def test_pipeline_flow_smoke_runs(monkeypatch, tmp_path):
    # Import the flow module under test
    from src.pipeline.flows import core as flow_core

    # Patch preflight to avoid external dependencies
    monkeypatch.setattr(
        flow_core,
        "run_preflight",
        lambda uri, username, password, database: {"gds": {"available": False}},
        raising=True,
    )

    # No-op DB setup/cleanup tasks
    monkeypatch.setattr(flow_core, "T_setup_schema_task", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(flow_core, "T_cleanup_task", lambda *a, **k: None, raising=True)

    # No-op code extraction/embedding/writes
    monkeypatch.setattr(flow_core, "T_extract_code_task", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(flow_core, "T_embed_files_task", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(flow_core, "T_embed_methods_task", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(flow_core, "T_write_graph_task", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(flow_core, "T_cleanup_artifacts_task", lambda *a, **k: None, raising=True)

    # No-op git and analytics
    monkeypatch.setattr(flow_core, "T_git_history_task", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(flow_core, "run_post_ingest_analytics", lambda *a, **k: None, raising=True)

    # Run the flow against a temp directory so clone path is not used
    flow_core.code_graph_flow(repo_url=str(tmp_path), cleanup=False)
