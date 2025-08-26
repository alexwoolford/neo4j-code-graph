#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar, cast

T = TypeVar("T")


def _tqdm_available() -> bool:
    try:
        return importlib.util.find_spec("tqdm") is not None
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
) -> Iterator[T]:
    """Yield items from iterable, displaying a progress bar when available.

    This implementation avoids constructing a tqdm iterator directly over
    generators (e.g., as_completed), and always closes the progress bar
    explicitly to prevent __del__-time AttributeErrors in some environments.
    """
    if _progress_disabled(disable) or not _tqdm_available():
        for item in iterable:
            yield item
        return

    try:
        from tqdm import tqdm as _tqdm
    except Exception:
        for item in iterable:
            yield item
        return

    if total is not None:
        _tqdm_func: Callable[..., Any] = cast(Callable[..., Any], _tqdm)
        pbar_kwargs: dict[str, Any] = {"total": total}
        if desc is not None:
            pbar_kwargs["desc"] = desc
        if unit is not None:
            pbar_kwargs["unit"] = unit
        pbar = _tqdm_func(**pbar_kwargs)  # type: ignore[call-arg]
        try:
            for item in iterable:
                yield item
                try:
                    pbar.update(1)
                except Exception:
                    # If updating fails, continue yielding without progress.
                    pass
        finally:
            try:
                pbar.close()
            except Exception:
                pass
        return

    # No total provided: delegate iteration to tqdm wrapper but handle failures.
    try:
        _tqdm_iter_func: Callable[..., Any] = cast(Callable[..., Any], _tqdm)
        iter_kwargs: dict[str, Any] = {}
        if desc is not None:
            iter_kwargs["desc"] = desc
        if unit is not None:
            iter_kwargs["unit"] = unit
        for item in _tqdm_iter_func(iterable, **iter_kwargs):  # type: ignore[call-arg]
            yield item
    except Exception:
        for item in iterable:
            yield item


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
    return iter(wrapped)
