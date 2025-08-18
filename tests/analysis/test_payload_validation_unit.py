#!/usr/bin/env python3

import pytest


def test_validate_methods_payload_success_and_failures():
    from src.analysis.payload_validation import (
        PayloadValidationError,
        validate_methods_payload,
    )

    # Success
    validate_methods_payload(
        [
            {
                "method_signature": "p.C#m():void",
                "name": "m",
                "class_name": "C",
            }
        ]
    )

    # Missing signature
    with pytest.raises(PayloadValidationError):
        validate_methods_payload([{"name": "m", "class_name": "C"}])
    # Missing name
    with pytest.raises(PayloadValidationError):
        validate_methods_payload([{"method_signature": "s", "class_name": "C"}])
    # Missing class_name
    with pytest.raises(PayloadValidationError):
        validate_methods_payload([{"method_signature": "s", "name": "m"}])


def test_validate_calls_payload_success_and_failures():
    from src.analysis.payload_validation import (
        PayloadValidationError,
        validate_calls_payload,
    )

    # Success (empty qualifier allowed but present)
    validate_calls_payload(
        [
            {
                "caller_signature": "a",
                "callee_signature": "b",
                "qualifier": "",
            }
        ]
    )

    with pytest.raises(PayloadValidationError):
        validate_calls_payload([{"callee_signature": "b", "qualifier": "x"}])
    with pytest.raises(PayloadValidationError):
        validate_calls_payload([{"caller_signature": "a", "qualifier": "x"}])
    with pytest.raises(PayloadValidationError):
        validate_calls_payload([{"caller_signature": "a", "callee_signature": "b"}])
