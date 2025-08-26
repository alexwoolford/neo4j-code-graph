#!/usr/bin/env python3

from __future__ import annotations

import os

from src.utils.progress import progress_iter, progress_range


def test_progress_iter_basic_iteration_without_tqdm(monkeypatch) -> None:
    monkeypatch.setenv("CODEGRAPH_PROGRESS", "off")
    items = list(progress_iter([1, 2, 3], total=3, desc="x"))
    assert items == [1, 2, 3]


def test_progress_range_basic() -> None:
    os.environ.pop("CODEGRAPH_PROGRESS", None)
    items = list(progress_range(0, 5))
    assert items == [0, 1, 2, 3, 4]
