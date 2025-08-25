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


@pytest.fixture(scope="session")
def neo4j_driver():
    """Session-scoped Neo4j driver using Testcontainers when available.

    Falls back to environment-driven connection (NEO4J_*) if Docker is not available.
    Skips politely if neither is configured.
    """
    if _has_docker():
        try:
            from testcontainers.neo4j import Neo4jContainer  # type: ignore

            with (
                Neo4jContainer(image="neo4j:5.26")
                .with_env("NEO4J_AUTH", "neo4j/test")
                .with_env("NEO4J_PLUGINS", '["gds","apoc"]')
                .with_env("NEO4J_dbms_security_procedures_unrestricted", "gds.*,apoc.*") as neo4j
            ):  # latest LTS with plugins
                with neo4j.get_driver() as driver:  # type: ignore[attr-defined]
                    # Export connection params so code under test using get_neo4j_config() works
                    import os

                    try:
                        bolt_port = neo4j.get_exposed_port(7687)  # type: ignore[attr-defined]
                    except Exception:
                        bolt_port = "7687"
                    os.environ["NEO4J_URI"] = f"bolt://localhost:{bolt_port}"
                    os.environ["NEO4J_USERNAME"] = "neo4j"
                    os.environ["NEO4J_PASSWORD"] = "test"
                    os.environ["NEO4J_DATABASE"] = "neo4j"
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
        return
    try:
        from testcontainers.neo4j import Neo4jContainer  # type: ignore
    except Exception:
        return

    neo4j = (
        Neo4jContainer(image="neo4j:5.26")
        .with_env("NEO4J_AUTH", "neo4j/test")
        .with_env("NEO4J_PLUGINS", '["gds","apoc"]')
        .with_env("NEO4J_dbms_security_procedures_unrestricted", "gds.*,apoc.*")
    )
    neo4j.start()
    import os as _os

    try:
        bolt_port = neo4j.get_exposed_port(7687)  # type: ignore[attr-defined]
    except Exception:
        bolt_port = "7687"
    _os.environ["NEO4J_URI"] = f"bolt://localhost:{bolt_port}"
    _os.environ["NEO4J_USERNAME"] = "neo4j"
    _os.environ["NEO4J_PASSWORD"] = "test"
    _os.environ["NEO4J_DATABASE"] = "neo4j"
    try:
        yield
    finally:
        try:
            neo4j.stop()
        except Exception:
            pass
