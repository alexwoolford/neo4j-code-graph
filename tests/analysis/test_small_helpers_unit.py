#!/usr/bin/env python3

import pytest


def test_get_database_batch_size_variants():
    from src.analysis.code_analysis import get_database_batch_size

    assert get_database_batch_size(has_embeddings=True) < get_database_batch_size()
    assert get_database_batch_size(estimated_size_mb=2) == 500
    assert get_database_batch_size(estimated_size_mb=0) == get_database_batch_size()


@pytest.mark.parametrize(
    "pkg,cls,method,params,ret,expected",
    [
        (
            "a.b",
            "C",
            "m",
            [{"type": "int"}, {"type": "String"}],
            "void",
            "a.b.C#m(int,String):void",
        ),
        (None, "C", "m", [], None, "C#m():void"),
        ("p", None, "f", [{"type": None}], "int", "p.f(?):int"),
        (
            "p.q",
            "Outer.Inner",
            "run",
            [{"type": "List<String>"}],
            None,
            "p.q.Outer.Inner#run(List<String>):void",
        ),
    ],
)
def test_build_method_signature_cases(pkg, cls, method, params, ret, expected):
    from src.analysis.code_analysis import build_method_signature

    assert build_method_signature(pkg, cls, method, params, ret) == expected


def test_extract_method_calls_simple_patterns():
    from src.analysis.code_analysis import _extract_method_calls

    code = """
class C {
  void m() {
    this.helper();
    Helper.staticCall();
    obj.instanceCall();
    super.toString();
    method();
  }
}
"""
    calls = _extract_method_calls(code, "C")
    names = {c["method_name"] for c in calls}
    types = {c["call_type"] for c in calls}
    # Ensure we captured a few varieties
    assert {"helper", "instanceCall", "toString", "method"}.issubset(names)
    assert {"this", "instance", "super", "same_class"}.issubset(types)


def test_determine_call_target_variants():
    from src.analysis.code_analysis import _determine_call_target

    assert _determine_call_target(None, "C") == ("C", "same_class")
    assert _determine_call_target("this", "C") == ("C", "this")
    assert _determine_call_target("super", "C") == ("super", "super")
    assert _determine_call_target("Helper", "C")[1] == "static"
    assert _determine_call_target("obj", "C")[1] == "instance"
