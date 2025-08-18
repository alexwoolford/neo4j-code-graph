#!/usr/bin/env python3

import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _prefect_stub_module():
    """Provide a lightweight stub for the `prefect` package in unit tests.

    This keeps fast unit tests independent from the actual Prefect runtime while
    allowing us to import `src.pipeline.prefect_flow` and patch task functions.
    """
    if "prefect" not in sys.modules:
        module = types.SimpleNamespace()

        def _decorator_factory(*_args, **_kwargs):
            def _decorator(fn):
                return fn

            return _decorator

        def _get_run_logger():
            class _L:
                def info(self, *args, **kwargs):
                    pass

                def warning(self, *args, **kwargs):
                    pass

            return _L()

        module.flow = _decorator_factory
        module.task = _decorator_factory
        module.get_run_logger = _get_run_logger
        sys.modules["prefect"] = module
    yield
