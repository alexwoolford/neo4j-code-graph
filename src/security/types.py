"""
Typed types for security-related data structures.
"""

from __future__ import annotations

from typing import TypedDict


class CleanCVE(TypedDict):
    """Minimal, cleaned CVE shape used throughout the pipeline.

    Derived from NVD CVE 2.0 responses and normalized in
    `CVECacheManager._extract_clean_cve_data`.
    """

    id: str
    description: str
    cvss_score: float
    severity: str
    published: str
    modified: str
