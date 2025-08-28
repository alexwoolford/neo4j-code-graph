#!/usr/bin/env python3

from __future__ import annotations


class _FakeSession:
    def __init__(self, fail_on: str | None = None):
        self.fail_on = fail_on

    class _Res:
        @staticmethod
        def consume():
            return None

    def run(self, query: str, **params):
        if self.fail_on and self.fail_on in query:
            raise RuntimeError("boom")
        return self._Res()


def test_explain_success_and_failure():
    from src.utils.cypher_validation import explain

    ok, err = explain(_FakeSession(), "RETURN 1")
    assert ok is True and err is None

    ok2, err2 = explain(_FakeSession(fail_on="EXPLAIN"), "RETURN 1")
    assert ok2 is False and isinstance(err2, str)


def test_run_validation_emits_expected_keys():
    from src.utils.cypher_validation import run_validation

    sess = _FakeSession()
    results = run_validation(sess)
    # Expect at least a subset of named checks to be present and True
    result_map = {name: ok for (name, ok, _err) in results}
    for key in [
        "simple_param",
        "unwind_list",
        "file_nodes",
        "import_nodes",
        "external_dep_link",
        "cve_impact_sample",
    ]:
        assert key in result_map and result_map[key] is True
