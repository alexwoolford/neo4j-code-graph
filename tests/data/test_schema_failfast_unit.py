#!/usr/bin/env python3

from __future__ import annotations

import pytest

from src.data.schema_management import ensure_constraints_exist_or_fail


class _Session:
    def __init__(self, existing: list[str]):
        self._existing = existing

    def run(self, query: str):  # type: ignore[override]
        class _Res:
            def __init__(self, names: list[str]):
                self._names = names

            def __iter__(self):
                for n in self._names:
                    yield {"name": n}

            @staticmethod
            def single():  # not used in this test
                return None

            @staticmethod
            def consume():
                return None

        if query.strip().upper().startswith("SHOW CONSTRAINTS"):
            return _Res(self._existing)
        # treat CREATE/DROP as no-ops
        return _Res([])


def test_ensure_constraints_exist_or_fail_raises_when_still_missing() -> None:
    # Simulate missing constraints; after "creation" they remain missing
    sess = _Session(existing=["file_path"])  # present only one
    with pytest.raises(RuntimeError) as exc:
        ensure_constraints_exist_or_fail(sess)  # type: ignore[arg-type]
    assert "Schema constraints missing" in str(exc.value)
