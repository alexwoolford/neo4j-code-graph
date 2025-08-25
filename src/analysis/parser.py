#!/usr/bin/env python3

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def build_method_signature(
    package_name: str | None,
    class_name: str | None,
    method_name: str,
    parameters: list[dict[str, Any]],
    return_type: str | None,
) -> str:
    """Build a stable method signature string for uniqueness and Bloom captions.

    Format: <package>.<class>#<method>(<paramType,...>):<returnType>
    Missing parts are omitted gracefully.
    """
    pkg = f"{package_name}." if package_name else ""
    cls = class_name or ""
    param_types: list[str] = []
    for p in parameters or []:
        t = p.get("type") if isinstance(p, dict) else None
        param_types.append(str(t) if t is not None else "?")
    params_str = ",".join(param_types)
    ret = return_type or "void"
    if cls:
        return f"{pkg}{cls}#{method_name}({params_str}):{ret}"
    return f"{pkg}{method_name}({params_str}):{ret}"


def extract_file_data(file_path: Path, repo_root: Path) -> dict[str, Any]:
    """Extract all data from a single Java file using Tree-sitter (primary parser).

    Delegates to `java_treesitter.extract_file_data` and preserves the output
    structure expected by downstream writers. On failure, returns a minimal
    payload so the caller can continue gracefully.
    """
    try:
        from src.analysis import java_treesitter as _jt  # type: ignore
    except Exception:
        _jt = None  # type: ignore

    if _jt is not None and hasattr(_jt, "extract_file_data"):
        try:
            return _jt.extract_file_data(file_path, repo_root)
        except Exception as e:  # pragma: no cover - unexpected parse failure
            rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
            logger.warning("Tree-sitter failed for %s: %s", rel_path, e)
            return _minimal_file_payload(rel_path)

    # If Tree-sitter module is unavailable, return a minimal structure
    rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
    logger.warning("Tree-sitter extractor not available; skipping %s", rel_path)
    return _minimal_file_payload(rel_path)


def _minimal_file_payload(rel_path: str) -> dict[str, Any]:
    return {
        "path": rel_path,
        "code": "",
        "methods": [],
        "classes": [],
        "interfaces": [],
        "imports": [],
        "language": "java",
        "ecosystem": "maven",
        "total_lines": 0,
        "code_lines": 0,
        "method_count": 0,
        "class_count": 0,
        "interface_count": 0,
    }


__all__ = [
    "build_method_signature",
    "extract_file_data",
]
