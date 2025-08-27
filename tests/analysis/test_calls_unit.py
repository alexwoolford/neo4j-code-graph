#!/usr/bin/env python3

from __future__ import annotations

from src.analysis.calls import _determine_call_target, extract_method_calls


def test_determine_call_target_same_class() -> None:
    target, call_type = _determine_call_target(None, "MyClass")
    assert target == "MyClass"
    assert call_type == "same_class"


def test_determine_call_target_this_and_super() -> None:
    t1, c1 = _determine_call_target("this", "C")
    t2, c2 = _determine_call_target("super", "C")
    assert (t1, c1) == ("C", "this")
    assert (t2, c2) == ("super", "super")


def test_determine_call_target_static_and_instance() -> None:
    ts, cs = _determine_call_target("Math", "C")
    ti, ci = _determine_call_target("helper", "C")
    assert (ts, cs) == ("Math", "static")
    assert (ti, ci) == ("helper", "instance")


def test_extract_method_calls_skips_keywords_and_constructors() -> None:
    code = """
    for(i=0;i<10;i++){
        Logger.info("x");
        helper.process(value);
        Math.max(a,b);
        new Thing();
    }
    """
    calls = extract_method_calls(code, "C")
    names = {c["method_name"] for c in calls}
    # 'for' and 'new' skipped; Logger.info kept (qualifier present), Math.max kept as static
    assert "process" in names
    assert "max" in names
    assert "for" not in names
    assert "new" not in names


def test_extract_method_calls_basic_and_filters():
    code = """
    void m() {
        this.foo();
        super.bar();
        Helper.baz();
        obj.qux();
        for(i=0;i<10;i++) {}
        return;
        NewType();  // constructor-like call should be ignored (capitalized)
    }
    """
    out = extract_method_calls(code, "Clazz")
    names = [(c["method_name"], c["call_type"]) for c in out]
    assert ("foo", "this") in names
    assert ("bar", "super") in names
    assert ("baz", "static") in names
    assert ("qux", "instance") in names
    # Keywords and capitalized names are filtered
    assert all(n not in {"for", "return", "NewType"} for n, _ in names)


def test_extract_method_calls_none_safe():
    assert extract_method_calls(None, "C") == []
