"""Pytest configuration to stabilize multiprocessing and support async tests.

- Switches multiprocessing to 'spawn' to avoid macOS shutdown issues.
- Disables semlock cleanup in resource_tracker to prevent KeyError noise.
- Provides a minimal async test runner when coroutine tests are detected.
"""

from __future__ import annotations

# Test session bootstrap tweaks to avoid spurious multiprocessing shutdown errors


def _configure_multiprocessing_start_method() -> None:
    try:
        import multiprocessing as mp

        # Use 'spawn' to avoid fork-related resource tracker glitches on macOS
        try:
            mp.set_start_method("spawn", force=True)
        except RuntimeError:
            pass

        # Silence resource_tracker KeyError on exit for semaphores
        try:
            from multiprocessing import resource_tracker

            # Remove semlock cleanup that can trigger KeyError at interpreter shutdown
            getattr(resource_tracker, "_CLEANUP_FUNCS", {}).pop("semlock", None)
        except Exception:
            pass
    except Exception:
        pass


_configure_multiprocessing_start_method()

import asyncio
import inspect
from typing import Any, Optional  # noqa: F401 (imported for potential future use)


def pytest_pyfunc_call(pyfuncitem) -> bool | None:  # type: ignore[override]
    test_function = pyfuncitem.obj
    if inspect.iscoroutinefunction(test_function):
        loop = asyncio.new_event_loop()
        try:
            # Build kwargs for the test function from available funcargs
            sig = inspect.signature(test_function)
            kwargs = {k: v for k, v in pyfuncitem.funcargs.items() if k in sig.parameters}
            loop.run_until_complete(test_function(**kwargs))
        finally:
            try:
                # Cancel lingering tasks to avoid warnings
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()
        return True
    return None


#!/usr/bin/env python3
import os

import pytest


def _has_docker() -> bool:
    # Basic signal for CI/local; Testcontainers needs a working Docker socket
    return os.path.exists("/var/run/docker.sock") or bool(os.getenv("DOCKER_HOST"))


# Start container and export env before test collection to avoid early wrong-auth attempts
_TC_CONTAINER = None


def pytest_sessionstart(session):  # type: ignore[override]
    global _TC_CONTAINER
    # If explicit env is present, attempt to bootstrap schema on that instance
    if os.getenv("NEO4J_URI") and os.getenv("NEO4J_USERNAME") and os.getenv("NEO4J_PASSWORD"):
        print("[tests] Using explicit NEO4J_* environment; verifying connectivity and schema...")
        try:
            from neo4j import GraphDatabase as _GD  # type: ignore

            from src.data.schema_management import setup_complete_schema  # type: ignore

            drv = _GD.driver(
                os.environ["NEO4J_URI"],
                auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            )
            try:
                drv.verify_connectivity()
                with drv.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as _s:
                    setup_complete_schema(_s)
            finally:
                drv.close()
        except Exception:
            pass
        return
    # Defer container startup to the autouse session fixture to avoid double-starting
    print("[tests] Deferring Neo4j Testcontainers startup to autouse fixture...")
    return


def pytest_sessionfinish(session, exitstatus):  # type: ignore[override]
    global _TC_CONTAINER
    if _TC_CONTAINER is not None:
        try:
            _TC_CONTAINER.stop()
        except Exception:
            pass


@pytest.fixture(scope="session")
def neo4j_driver():
    """Session-scoped Neo4j driver using Testcontainers when available.

    Falls back to environment-driven connection (NEO4J_*) if Docker is not available.
    Skips politely if neither is configured.
    """
    # If autouse fixture already exported env, prefer that to avoid starting
    # a second container. This keeps one DB per session.
    import os as _os_mod

    if (
        _os_mod.getenv("NEO4J_URI")
        and _os_mod.getenv("NEO4J_USERNAME")
        and _os_mod.getenv("NEO4J_PASSWORD")
    ):
        try:
            from neo4j import GraphDatabase  # type: ignore

            uri = _os_mod.environ["NEO4J_URI"]
            user = _os_mod.environ["NEO4J_USERNAME"]
            pwd = _os_mod.environ["NEO4J_PASSWORD"]
            drv = GraphDatabase.driver(uri, auth=(user, pwd))
            drv.verify_connectivity()
            yield drv
            drv.close()
            return
        except Exception:
            pass

    if _has_docker():
        try:
            from testcontainers.neo4j import Neo4jContainer  # type: ignore

            def _make_container() -> Neo4jContainer:  # type: ignore[name-defined]
                return (
                    Neo4jContainer(image="neo4j:5.26-enterprise")
                    .with_env("NEO4J_ACCEPT_LICENSE_AGREEMENT", "yes")
                    .with_env("NEO4J_AUTH", "neo4j/neo4j12345")
                    .with_env("NEO4J_PLUGINS", '["graph-data-science","apoc"]')
                    .with_env("NEO4J_dbms_security_procedures_unrestricted", "gds.*,apoc.*")
                )

            with _make_container() as neo4j:  # latest LTS with plugins
                with neo4j.get_driver() as driver:  # type: ignore[attr-defined]
                    # Export connection params so code under test using get_neo4j_config() works
                    import os

                    try:
                        bolt_port = neo4j.get_exposed_port(7687)  # type: ignore[attr-defined]
                    except Exception:
                        bolt_port = "7687"
                    os.environ["NEO4J_URI"] = f"bolt://127.0.0.1:{bolt_port}"
                    os.environ["NEO4J_USERNAME"] = "neo4j"
                    os.environ["NEO4J_PASSWORD"] = "neo4j12345"
                    os.environ["NEO4J_DATABASE"] = "neo4j"
                    # Wait for DB to be ready
                    try:
                        driver.verify_connectivity()
                    except Exception:
                        import time as _t

                        for _ in range(45):
                            _t.sleep(2)
                            try:
                                driver.verify_connectivity()
                                break
                            except Exception:
                                continue
                    yield driver
                return
        except Exception as e:  # fall through to env-based driver
            print(f"[tests] Testcontainers Neo4j not available: {e}")

    # Fallback to explicit env-configured instance
    try:
        from neo4j import GraphDatabase  # type: ignore

        from src.utils.neo4j_utils import get_neo4j_config  # type: ignore

        uri, user, pwd, db = get_neo4j_config()
        drv = GraphDatabase.driver(uri, auth=(user, pwd))
        try:
            drv.verify_connectivity()
        except Exception:
            drv.close()
            pytest.skip("Neo4j not available and Docker not usable for Testcontainers")
        else:
            yield drv
            drv.close()
    except Exception:
        pytest.skip("Neo4j not available and Docker not usable for Testcontainers")


# Start a Neo4j container for the whole session and export NEO4J_* so tests that
# don't request the driver still connect to a live DB (autouse to avoid localhost fallbacks)
@pytest.fixture(scope="session", autouse=True)
def _ensure_neo4j_env_for_session():
    if not _has_docker():
        # No Docker available; do not attempt to start a container
        # but still yield to satisfy fixture contract
        yield
        return
    try:
        from testcontainers.neo4j import Neo4jContainer  # type: ignore
    except Exception:
        # testcontainers not installed/usable; no-op
        yield
        return

    def _make_container() -> Neo4jContainer:  # type: ignore[name-defined]
        return (
            Neo4jContainer(image="neo4j:5.26-enterprise")
            .with_env("NEO4J_ACCEPT_LICENSE_AGREEMENT", "yes")
            .with_env("NEO4J_AUTH", "neo4j/neo4j12345")
            .with_env("NEO4J_PLUGINS", '["graph-data-science","apoc"]')
            .with_env("NEO4J_dbms_security_procedures_unrestricted", "gds.*,apoc.*")
        )

    print("[tests] Starting Neo4j Testcontainers (session autouse)...")
    neo4j = _make_container()
    neo4j.start()
    import os as _os

    try:
        bolt_port = neo4j.get_exposed_port(7687)  # type: ignore[attr-defined]
    except Exception:
        bolt_port = "7687"
    _os.environ["NEO4J_URI"] = f"bolt://127.0.0.1:{bolt_port}"
    _os.environ["NEO4J_USERNAME"] = "neo4j"
    _os.environ["NEO4J_PASSWORD"] = "neo4j12345"
    _os.environ["NEO4J_DATABASE"] = "neo4j"
    # Wait for DB to be ready (emit periodic progress)
    try:
        from neo4j import GraphDatabase as _GD

        _drv = _GD.driver(_os.environ["NEO4J_URI"], auth=("neo4j", "neo4j12345"))
        import time as _t

        for i in range(45):
            try:
                _drv.verify_connectivity()
                break
            except Exception:
                if i % 10 == 0:
                    print("[tests] Waiting for Neo4j container...")
                _t.sleep(2)
        print(f"[tests] Neo4j ready at {_os.environ['NEO4J_URI']}")
        _drv.close()
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            neo4j.stop()
        except Exception:
            pass


# Function-scoped cleanup to avoid per-test manual MATCH DETACH blocks
@pytest.fixture(autouse=True)
def _reset_db_between_tests(neo4j_driver):
    try:
        with neo4j_driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
    except Exception:
        pass


# Ensure schema exists for all live tests, regardless of how the DB is provided
@pytest.fixture(scope="session", autouse=True)
def _ensure_schema_for_live_tests():
    """Ensure schema exists for live tests without depending on fixture scope.

    This avoids scope conflicts with class-scoped neo4j_driver fixtures in some tests.
    """
    try:
        import os as _os

        from neo4j import GraphDatabase as _GD  # type: ignore

        from src.data.schema_management import setup_complete_schema  # type: ignore

        uri = _os.getenv("NEO4J_URI")
        user = _os.getenv("NEO4J_USERNAME")
        pwd = _os.getenv("NEO4J_PASSWORD")
        db = _os.getenv("NEO4J_DATABASE", "neo4j")
        if not (uri and user and pwd):
            return
        drv = _GD.driver(uri, auth=(user, pwd))
        try:
            with drv.session(database=db) as _s:
                setup_complete_schema(_s)
        finally:
            drv.close()
    except Exception:
        pass


# Mini graph fixture for Method/CALLS
@pytest.fixture
def mini_method_call_graph(neo4j_driver):
    """Create a tiny Method/CALLS graph and yield signatures.

    Nodes:
      - com.example.A#a():void (id=1)
      - com.example.B#b():void (id=2)
      - com.example.C#c():void (id=3)
    Relationships:
      - A CALLS B
      - A CALLS C
    """
    with neo4j_driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        s.run(
            """
            UNWIND $rows AS r
            MERGE (m:Method {method_signature: r.sig})
            ON CREATE SET m.id = r.id, m.name = r.name, m.class_name = r.cls, m.file = r.file
            """,
            rows=[
                {
                    "sig": "com.example.A#a():void",
                    "id": 1,
                    "name": "a",
                    "cls": "A",
                    "file": "src/main/java/com/example/A.java",
                },
                {
                    "sig": "com.example.B#b():void",
                    "id": 2,
                    "name": "b",
                    "cls": "B",
                    "file": "src/main/java/com/example/B.java",
                },
                {
                    "sig": "com.example.C#c():void",
                    "id": 3,
                    "name": "c",
                    "cls": "C",
                    "file": "src/main/java/com/example/C.java",
                },
            ],
        ).consume()
        s.run(
            """
            MATCH (a:Method {method_signature:$a}), (b:Method {method_signature:$b})
            MERGE (a)-[:CALLS]->(b)
            """,
            a="com.example.A#a():void",
            b="com.example.B#b():void",
        ).consume()
        s.run(
            """
            MATCH (a:Method {method_signature:$a}), (c:Method {method_signature:$c})
            MERGE (a)-[:CALLS]->(c)
            """,
            a="com.example.A#a():void",
            c="com.example.C#c():void",
        ).consume()
    yield {
        "A": "com.example.A#a():void",
        "B": "com.example.B#b():void",
        "C": "com.example.C#c():void",
    }
