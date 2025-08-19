from src.analysis.code_analysis import _extract_method_calls


def test_extract_method_calls_various_patterns():
    # same-class call (no qualifier) -> same_class
    calls = _extract_method_calls("b();", "A")
    assert {c["method_name"] for c in calls} == {"b"}
    assert calls[0]["call_type"] == "same_class"

    # this-qualified call -> this
    calls = _extract_method_calls("this.b();", "A")
    assert calls and calls[0]["call_type"] == "this"

    # super-qualified call -> super
    calls = _extract_method_calls("super.toString();", "A")
    assert calls and calls[0]["call_type"] == "super"

    # static-qualified call with capitalized class -> static
    calls = _extract_method_calls("Util.doIt();", "A")
    assert calls and calls[0]["call_type"] == "static" and calls[0]["qualifier"] == "Util"

    # constructor-like (Capitalized method) is ignored
    calls = _extract_method_calls("new Foo(); Foo();", "A")
    assert all(c["method_name"] != "Foo" for c in calls)

    # keywords should be skipped
    calls = _extract_method_calls("return(x); while(x) doWork();", "A")
    assert any(c["method_name"] == "doWork" for c in calls)
