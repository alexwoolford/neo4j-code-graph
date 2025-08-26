#!/usr/bin/env python3

from __future__ import annotations

from src.analysis.calls import extract_method_calls
from src.analysis.parser import build_method_signature


def test_build_method_signature_with_generics_and_arrays() -> None:
    sig = build_method_signature(
        package_name="p.q",
        class_name="Outer.Inner",
        method_name="run",
        parameters=[{"type": "List<String>"}, {"type": "int[]"}],
        return_type=None,
    )
    assert sig == "p.q.Outer.Inner#run(List<String>,int[]):void"


def test_extract_method_calls_chained_and_this_calls() -> None:
    code = "this.helper().next().finalize(); obj.call();"
    calls = extract_method_calls(code, "C")
    names = [c["method_name"] for c in calls]
    # chained calls capture each identifier followed by '('; uppercase starters skipped
    assert "helper" in names and "next" in names and "finalize" in names and "call" in names
