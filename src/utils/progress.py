#!/usr/bin/env python3

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def _tqdm_available() -> bool:
    try:
        import tqdm  # noqa: F401

        return True
    except Exception:
        return False


def _progress_disabled(explicit_disable: bool | None) -> bool:
    if explicit_disable is True:
        return True
    flag = os.getenv("CODEGRAPH_PROGRESS", "").lower().strip()
    return flag in {"0", "false", "off", "no"}


def progress_iter(
    iterable: Iterable[T],
    *,
    total: int | None = None,
    desc: str | None = None,
    unit: str | None = None,
    disable: bool | None = None,
) -> Iterable[T]:
    """Wrap an iterable with a progress bar when available.

    - Respects CODEGRAPH_PROGRESS env ("off"/"false" to disable)
    - Falls back to the plain iterable if tqdm is unavailable
    """
    if _progress_disabled(disable) or not _tqdm_available():
        return iterable
    try:
        from tqdm import tqdm

        return tqdm(iterable, total=total, desc=desc, unit=unit)
    except Exception:
        return iterable


def progress_range(
    start: int,
    stop: int,
    step: int = 1,
    *,
    total: int | None = None,
    desc: str | None = None,
    unit: str | None = None,
    disable: bool | None = None,
) -> Iterator[int]:
    """Range with progress display when available.

    Computes total automatically if not provided.
    """
    rng = range(start, stop, step)
    computed_total: int | None
    if total is not None:
        computed_total = total
    else:
        try:
            length = max((stop - start + (step - 1)) // step, 0)
            computed_total = int(length)
        except Exception:
            computed_total = None
    wrapped = progress_iter(rng, total=computed_total, desc=desc, unit=unit, disable=disable)
    # typing: progress_iter returns Iterable[int]; ensure Iterator for callers that rely on it
    return iter(wrapped)
