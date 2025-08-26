#!/usr/bin/env python3

from __future__ import annotations

from typing import Any, Literal

import src.pipeline.tasks.db_tasks as tasks


class _FakeSession:
    def __init__(self):
        self.runs: list[tuple[str, dict[str, Any]]] = []

    def run(self, q: str, params: dict[str, Any] | None = None) -> Any:  # noqa: D401
        self.runs.append((" ".join(q.split()), params or {}))

        class _R:
            def consume(self) -> None:
                return None

        return _R()

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False


class _FakeDriver:
    def __init__(self):
        self.sessions: list[_FakeSession] = []

    def session(self, database: str) -> _FakeSession:  # noqa: D401
        s = _FakeSession()
        self.sessions.append(s)
        return s

    def __enter__(self) -> _FakeDriver:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False


def _fake_driver_factory(uri: str, user: str, pwd: str) -> _FakeDriver:
    return _FakeDriver()


def _resolved() -> tuple[str, str, str, str]:
    return ("bolt://x:7687", "u", "p", "neo4j")


class _Log:
    def info(self, *args: Any, **kwargs: Any) -> None:
        return None

    def warning(self, *args: Any, **kwargs: Any) -> None:
        return None


def _get_logger() -> Any:
    return _Log()


def test_setup_schema_task_invokes_setup(monkeypatch: Any) -> None:
    called = {"count": 0}

    def _fake_setup(session: Any) -> None:  # noqa: D401
        called["count"] += 1

    monkeypatch.setattr(tasks, "setup_complete_schema", _fake_setup)
    monkeypatch.setattr(tasks, "create_neo4j_driver", _fake_driver_factory)
    monkeypatch.setattr(tasks, "get_run_logger", _get_logger)

    tasks.setup_schema_task.fn("bolt://x", "u", "p", "neo4j")
    assert called["count"] == 1


def test_selective_cleanup_task_calls_cleanup(monkeypatch: Any) -> None:
    called = {"count": 0}

    def _fake_sel(session: Any, dry_run: bool) -> None:  # noqa: D401
        called["count"] += 1

    monkeypatch.setattr(tasks, "create_neo4j_driver", _fake_driver_factory)
    monkeypatch.setattr(tasks, "resolve_neo4j_args", _resolved)
    monkeypatch.setattr("src.utils.cleanup.selective_cleanup", _fake_sel)
    monkeypatch.setattr(tasks, "get_run_logger", _get_logger)

    tasks.selective_cleanup_task.fn("bolt://x", "u", "p", "neo4j")
    assert called["count"] == 1


def test_git_history_task_passes_repo_and_creds(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def _fake_load_history(**kwargs: Any) -> None:  # noqa: D401
        captured.update(kwargs)

    monkeypatch.setattr(tasks, "load_history", _fake_load_history)
    monkeypatch.setattr(tasks, "resolve_neo4j_args", _resolved)
    monkeypatch.setattr(tasks, "get_run_logger", _get_logger)

    tasks.git_history_task.fn("/tmp/repo", None, None, None, None)
    assert captured["repo_url"] == "/tmp/repo"
    assert captured["uri"] == "bolt://x:7687"
    assert captured["username"] == "u"
    assert captured["database"] == "neo4j"


def test_similarity_and_louvain_tasks_call_helpers(monkeypatch: Any) -> None:
    calls = {"idx": 0, "knn": 0, "louv": 0}

    class _GDS:
        def __init__(
            self,
            uri: str,
            auth: tuple[str, str],
            database: str,
            arrow: bool,
        ):  # noqa: D401
            pass

        def run_cypher(self, q: str, params: dict[str, Any] | None = None) -> None:  # noqa: D401
            return None

        def close(self) -> None:
            return None

    def _idx(gds: Any) -> None:  # noqa: D401
        calls["idx"] += 1

    def _knn(gds: Any, top_k: int, cutoff: float) -> None:  # noqa: D401
        calls["knn"] += 1

    def _louv(gds: Any, threshold: float) -> None:  # noqa: D401
        calls["louv"] += 1

    monkeypatch.setenv("NEO4J_URI", "bolt://x:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setattr("graphdatascience.GraphDataScience", _GDS)
    monkeypatch.setattr(tasks, "sim_create_index", _idx)
    monkeypatch.setattr(tasks, "sim_run_knn", _knn)
    monkeypatch.setattr(tasks, "sim_run_louvain", _louv)
    monkeypatch.setattr(tasks, "get_run_logger", _get_logger)

    tasks.similarity_task.fn(None, None, None, None)
    tasks.louvain_task.fn(None, None, None, None)
    assert calls["idx"] == 1 and calls["knn"] == 1 and calls["louv"] == 1


def test_centrality_task_calls_algorithms(monkeypatch: Any) -> None:
    calls = {"proj": 0, "pr": 0, "bt": 0, "deg": 0}

    class _Graph:
        def drop(self) -> None:
            return None

    class _GDS:
        def __init__(
            self,
            uri: str,
            auth: tuple[str, str],
            database: str,
            arrow: bool,
        ):  # noqa: D401
            pass

        def run_cypher(self, q: str, params: dict[str, Any] | None = None) -> None:  # noqa: D401
            return None

        def close(self) -> None:
            return None

    def _proj(gds: Any) -> _Graph:  # noqa: D401
        calls["proj"] += 1
        return _Graph()

    def _pr(gds: Any, graph: Any, top_n: int, write_back: bool) -> None:  # noqa: D401
        calls["pr"] += 1

    def _bt(gds: Any, graph: Any, top_n: int, write_back: bool) -> None:  # noqa: D401
        calls["bt"] += 1

    def _deg(gds: Any, graph: Any, top_n: int, write_back: bool) -> None:  # noqa: D401
        calls["deg"] += 1

    monkeypatch.setenv("NEO4J_URI", "bolt://x:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setattr("graphdatascience.GraphDataScience", _GDS)
    monkeypatch.setattr(tasks, "cent_create_graph", _proj)
    monkeypatch.setattr(tasks, "cent_pagerank", _pr)
    monkeypatch.setattr(tasks, "cent_betweenness", _bt)
    monkeypatch.setattr(tasks, "cent_degree", _deg)
    monkeypatch.setattr(tasks, "get_run_logger", _get_logger)

    tasks.centrality_task.fn(None, None, None, None)
    assert all(v == 1 for v in calls.values())


def test_cve_task_uses_analyzer_flow(monkeypatch: Any) -> None:
    called = {"built": 0, "impact": 0}

    class _FakeMgr:
        def fetch_targeted_cves(self, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: D401
            return [{"id": "CVE-1"}]

    class _Analyzer:
        def __init__(self, driver: Any, database: str):  # noqa: D401
            self.cve_manager = _FakeMgr()

        def get_cache_status(self) -> None:
            return None

        def extract_codebase_dependencies(self) -> tuple[dict[str, set[str]], set[str]]:
            return ({"maven": {"org.example:json:1.0.0"}}, {"java"})

        def create_universal_component_search_terms(
            self,
            deps: dict[str, set[str]],
        ) -> list[str]:  # noqa: D401
            return ["org.example json"]

        def create_vulnerability_graph(self, cve_data: list[dict[str, Any]]) -> int:  # noqa: D401
            called["built"] += 1
            return 1

        def analyze_vulnerability_impact(self, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: D401
            called["impact"] += 1
            return []

        def generate_impact_report(self, impact: list[dict[str, Any]]) -> None:  # noqa: D401
            return None

    monkeypatch.setenv("NVD_API_KEY", "x")
    monkeypatch.setenv("NEO4J_URI", "bolt://x:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setattr(tasks, "CVEAnalyzer", _Analyzer)
    monkeypatch.setattr(tasks, "create_neo4j_driver", _fake_driver_factory)
    monkeypatch.setattr(tasks, "get_run_logger", _get_logger)

    tasks.cve_task.fn(None, None, None, None)
    assert called["built"] == 1 and called["impact"] == 1
