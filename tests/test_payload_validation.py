from __future__ import annotations

import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


add_src_to_path()

from analysis.payload_validation import (  # noqa: E402
    PayloadValidationError,
    validate_calls_payload,
    validate_methods_payload,
)


def test_validate_methods_payload_passes_on_valid_items():
    methods = [
        {"method_signature": "a.A.m():void", "name": "m", "class_name": "A"},
        {"method_signature": "b.B.n(int):int", "name": "n", "class_name": "B"},
    ]
    validate_methods_payload(methods)


def test_validate_methods_payload_raises_on_missing_signature():
    methods = [{"name": "m", "class_name": "A"}]
    try:
        validate_methods_payload(methods)
        assert False, "Expected PayloadValidationError"
    except PayloadValidationError as e:
        assert "method_signature" in str(e)


def test_validate_calls_payload_requires_qualifier_and_signatures():
    good = [
        {
            "caller_signature": "a.A.m():void",
            "callee_signature": "b.B.n():void",
            "qualifier": "B",
        }
    ]
    validate_calls_payload(good)

    bad_missing_qual = [{"caller_signature": "x", "callee_signature": "y"}]
    try:
        validate_calls_payload(bad_missing_qual)
        assert False, "Expected PayloadValidationError for qualifier"
    except PayloadValidationError as e:
        assert "qualifier" in str(e)
