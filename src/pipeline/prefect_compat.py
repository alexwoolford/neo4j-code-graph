"""Thin compatibility layer for Prefect 2 APIs used by the pipeline.

In environments where Prefect is not installed (e.g., some unit test runs,
docs generation, or IDE inspections), we provide harmless fallbacks so modules
can be imported without errors while still type-checking and executing in
Prefect-enabled contexts.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

try:  # Prefer real Prefect when available
    from prefect import flow as flow  # type: ignore
    from prefect import get_run_logger as get_run_logger  # type: ignore
    from prefect import task as task  # type: ignore
except Exception:  # pragma: no cover - used only when Prefect is absent

    def task(*_args: Any, **_kwargs: Any) -> Callable[[Callable[..., T]], Callable[..., T]]:
        def _decorator(fn: Callable[..., T]) -> Callable[..., T]:
            return fn

        return _decorator

    def flow(*_args: Any, **_kwargs: Any) -> Callable[[Callable[..., T]], Callable[..., T]]:
        def _decorator(fn: Callable[..., T]) -> Callable[..., T]:
            return fn

        return _decorator

    def get_run_logger() -> logging.Logger:
        return logging.getLogger(__name__)
