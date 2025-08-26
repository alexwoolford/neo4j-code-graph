#!/usr/bin/env python3

from __future__ import annotations

from src.analysis.parser import build_method_signature


def test_build_method_signature_with_full_components() -> None:
    sig = build_method_signature(
        package_name="com.example.app",
        class_name="MyClass",
        method_name="doWork",
        parameters=[{"type": "int"}, {"type": "String"}],
        return_type="boolean",
    )
    assert sig == "com.example.app.MyClass#doWork(int,String):boolean"


def test_build_method_signature_without_class_omits_class_delimiter() -> None:
    sig = build_method_signature(
        package_name="com.example",
        class_name=None,
        method_name="fn",
        parameters=[{"type": "int"}],
        return_type="void",
    )
    assert sig == "com.example.fn(int):void"


def test_build_method_signature_handles_missing_param_types() -> None:
    sig = build_method_signature(
        package_name=None,
        class_name="C",
        method_name="m",
        parameters=[{}, {"foo": "bar"}],
        return_type=None,
    )
    # Unknown types are represented as '?', default return is 'void'
    assert sig == "C#m(?,?):void"
