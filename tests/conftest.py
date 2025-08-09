#!/usr/bin/env python3
"""
Pytest configuration for running async tests without requiring pytest-asyncio.

If pytest-asyncio is installed, its plugin will take precedence. Otherwise,
this hook will detect coroutine test functions and run them in a fresh event
loop, enabling async tests to execute in local environments without extra
plugins.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any  # noqa: F401 (imported for potential future use)


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
