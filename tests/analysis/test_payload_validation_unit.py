#!/usr/bin/env python3

from __future__ import annotations

import pytest

from src.analysis.payload_validation import (
    PayloadValidationError,
    validate_calls_payload,
    validate_methods_payload,
)


def test_validate_methods_payload_success():
    methods = [
        {"method_signature": "pkg.Class#m()", "name": "m", "class_name": "Class"},
        {"method_signature": "pkg.C#n()", "name": "n", "class_name": "C"},
    ]
    validate_methods_payload(methods)  # should not raise


@pytest.mark.parametrize(
    "bad",
    [
        [{"name": "m", "class_name": "C"}],
        [{"method_signature": " ", "name": "m", "class_name": "C"}],
        [{"method_signature": "sig", "class_name": "C"}],
        [{"method_signature": "sig", "name": "m"}],
    ],
)
def test_validate_methods_payload_errors(bad):
    with pytest.raises(PayloadValidationError):
        validate_methods_payload(bad)


def test_validate_calls_payload_success():
    calls = [
        {"caller_signature": "A#a()", "callee_signature": "B#b()", "qualifier": "this"},
        {"caller_signature": "A#a()", "callee_signature": "A#c()", "qualifier": ""},
    ]
    validate_calls_payload(calls)


@pytest.mark.parametrize(
    "bad",
    [
        [{"callee_signature": "B#b()", "qualifier": "x"}],
        [{"caller_signature": "A#a()", "qualifier": "x"}],
        [{"caller_signature": "A#a()", "callee_signature": "B#b()"}],
    ],
)
def test_validate_calls_payload_errors(bad):
    with pytest.raises(PayloadValidationError):
        validate_calls_payload(bad)
