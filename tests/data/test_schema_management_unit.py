#!/usr/bin/env python3

from __future__ import annotations


class _FakeSession:
    def __init__(self):
        self.runs: list[str] = []

    class _Res:
        def __init__(self, rows):
            self._rows = rows

        def __iter__(self):
            yield from self._rows

    def run(self, q: str):
        self.runs.append(" ".join(q.split()))
        # SHOW CONSTRAINTS → return existing constraints
        if q.strip().upper().startswith("SHOW CONSTRAINTS"):
            # Return only a subset so ensure_constraints detects missing
            return self._Res(
                [
                    {"name": "file_path", "labelsOrTypes": ["File"], "properties": ["path"]},
                    {
                        "name": "developer_email",
                        "labelsOrTypes": ["Developer"],
                        "properties": ["email"],
                    },
                ]
            )
        return self._Res([])


def test_ensure_constraints_attempts_setup_then_verifies():
    from src.data.schema_management import ensure_constraints_exist_or_fail

    sess = _FakeSession()
    # First call should detect missing constraints and try to create schema, then verify again
    try:
        ensure_constraints_exist_or_fail(sess)
    except RuntimeError:
        # It's fine if it raises due to still missing after creation; we only assert behavior below
        pass

    # Should have invoked CREATE statements (constraints + indexes) and verification twice
    joined = "\n".join(sess.runs)
    assert "CREATE CONSTRAINT file_path IF NOT EXISTS" in joined
    assert "CREATE INDEX method_name IF NOT EXISTS" in joined
    assert joined.count("SHOW CONSTRAINTS") >= 2
