"""Validation helpers for write payloads used by code_analysis writers.

These functions enforce required fields before Cypher execution so that
we fail fast during unit tests and in dry-run pipelines, without requiring
Neo4j to surface null-property errors at MERGE time.
"""

from typing import Dict, Iterable


class PayloadValidationError(ValueError):
    pass


def validate_methods_payload(methods: Iterable[Dict]) -> None:
    """Ensure methods have required fields prior to writing.

    Required fields:
      - method_signature (non-empty string)
      - name
      - class_name
    """
    for idx, m in enumerate(methods):
        sig = m.get("method_signature")
        if not isinstance(sig, str) or not sig.strip():
            raise PayloadValidationError(f"Method at index {idx} missing method_signature")
        if not m.get("name"):
            raise PayloadValidationError(f"Method at index {idx} missing name")
        if not m.get("class_name"):
            raise PayloadValidationError(f"Method at index {idx} missing class_name")


def validate_calls_payload(calls: Iterable[Dict]) -> None:
    """Ensure CALLS relationships have required fields.

    Required fields:
      - caller_signature
      - callee_signature
      - qualifier (not None; may be empty string for unqualified calls)
    """
    for idx, c in enumerate(calls):
        if not c.get("caller_signature"):
            raise PayloadValidationError(f"Call at index {idx} missing caller_signature")
        if not c.get("callee_signature"):
            raise PayloadValidationError(f"Call at index {idx} missing callee_signature")
        if "qualifier" not in c or c.get("qualifier") is None:
            raise PayloadValidationError(f"Call at index {idx} missing qualifier")
