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
