#!/usr/bin/env python3

from unittest.mock import patch


def test_flow_wiring_smoke(tmp_path):
    """Fast smoke test: ensure flow wires tasks together without heavy work.

    We stub task entrypoints to avoid real cloning, parsing, embeddings, or Neo4j work.
    """
    from src.pipeline import prefect_flow as pf

    # Create a dummy local repo directory to avoid git clone
    repo_dir = tmp_path / "dummy_repo"
    repo_dir.mkdir()

    # Replace heavy tasks with no-ops that track calls
    calls = []

    def _mark(name):
        def _fn(*args, **kwargs):
            calls.append(name)
            return None

        return _fn

    # Patch Prefect tasks' .submit/.result for the ones using async submission
    class _DummyFuture:
        def result(self):
            return None

    def _submit_stub(*_a, **_k):
        return _DummyFuture()

    with (
        patch.object(pf, "setup_schema_task", side_effect=_mark("setup_schema")),
        patch.object(pf, "cleanup_task", side_effect=_mark("cleanup")),
        patch.object(pf, "clone_repo_task", side_effect=lambda url: str(repo_dir)),
        patch.object(pf, "extract_code_task", side_effect=_mark("extract_code")),
        patch.object(pf, "embed_files_task", side_effect=_mark("embed_files")),
        patch.object(pf, "embed_methods_task", side_effect=_mark("embed_methods")),
        patch.object(pf, "write_graph_task", side_effect=_mark("write_graph")),
        patch.object(pf, "cleanup_artifacts_task", side_effect=_mark("cleanup_artifacts")),
        patch.object(pf, "git_history_task", side_effect=_mark("git_history")),
        patch.object(pf, "coupling_task", side_effect=_mark("coupling")),
        patch.object(pf, "similarity_task"),
        patch.object(pf, "louvain_task"),
        patch.object(pf, "centrality_task"),
        patch.object(pf, "cve_task"),
    ):
        # Patch .submit on the three tasks used that way to return a dummy future
        pf.similarity_task.submit = _submit_stub  # type: ignore[attr-defined]
        pf.louvain_task.submit = _submit_stub  # type: ignore[attr-defined]
        pf.centrality_task.submit = _submit_stub  # type: ignore[attr-defined]
        pf.cve_task.submit = _submit_stub  # type: ignore[attr-defined]

        pf.code_graph_flow(repo_url=str(repo_dir), cleanup=True)

    # Ensure the critical stages ran in expected order (prefix check is sufficient)
    assert calls[:3] == ["setup_schema", "cleanup", "extract_code"]
    assert "write_graph" in calls
    assert "git_history" in calls
    assert "coupling" in calls
