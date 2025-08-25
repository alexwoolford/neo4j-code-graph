#!/usr/bin/env python3

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

JAVA_KEYWORDS_TO_SKIP = {
    "i",
    "while",
    "for",
    "switch",
    "catch",
    "synchronized",
    "return",
    "throw",
    "new",
    "assert",
    "super",
    "this",
}


def extract_method_calls(
    method_code: str | None, containing_class: str | None
) -> list[dict[str, Any]]:
    if not method_code:
        return []

    method_calls: list[dict[str, Any]] = []
    try:
        call_pattern = r"(?:(\w+)\.)?(\w+)\s*\("
        matches = re.finditer(call_pattern, method_code)

        for match in matches:
            qualifier = match.group(1)
            method_name = match.group(2)

            if method_name.lower() in JAVA_KEYWORDS_TO_SKIP:
                continue
            if method_name[0].isupper():
                continue

            target_class, call_type = _determine_call_target(qualifier, containing_class)
            method_calls.append(
                {
                    "method_name": method_name,
                    "target_class": target_class,
                    "qualifier": qualifier,
                    "call_type": call_type,
                }
            )
    except Exception as e:
        logger.debug("Error parsing method calls in %s: %s", containing_class, e)

    return method_calls


def _determine_call_target(
    qualifier: str | None, containing_class: str | None
) -> tuple[str | None, str]:
    if qualifier is None:
        return containing_class, "same_class"
    if qualifier == "this":
        return containing_class, "this"
    if qualifier == "super":
        return "super", "super"
    if qualifier[0].isupper():
        return qualifier, "static"
    return qualifier, "instance"


__all__ = [
    "extract_method_calls",
]
