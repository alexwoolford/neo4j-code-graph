"""Response contract for the curated code-graph MCP server.

Every tool returns one JSON object built by :func:`build_envelope`::

    {
      "schema_version": "1.0",
      "tool": "cve_reachability",
      "summary": "<one human line>",
      "row_count": 12,
      "truncated": false,
      "caveats": ["Java only.", "CALLS is receiver-class + arity matched; ..."],
      "rows": [ {stable snake_case keys} ]
    }

Versioning: additive keys bump the minor, renames/removals bump the major.

Version history
---------------
- 1.0 — initial contract (schema_version, tool, summary, row_count, truncated,
  caveats, rows).

This module is pure: no Neo4j, no Cypher, no I/O. It also carries the shared
argument-validation helpers (:func:`parse_gav`, :func:`validate_max_hops`) so
they can be unit-tested without a database.
"""

from __future__ import annotations

from typing import Any

TOOL_SCHEMA_VERSION = "1.0"

# Honesty caveats repeated in-band on every response (agents that only read
# payloads still see the scope + soundness ceiling). The same two sentences are
# appended to every tool description.
JAVA_ONLY_CAVEAT = "Java only."
SOUNDNESS_CAVEAT = (
    "CALLS is receiver-class + arity matched; no reflection, DI, or dynamic "
    "dispatch — ranked triage, not proof."
)

# Convenience: the trailing scope sentence appended to each tool description.
SCOPE_SENTENCE = f"{JAVA_ONLY_CAVEAT} {SOUNDNESS_CAVEAT}"

# Var-length CALLS bound accepted by the reachability queries (mirrors the
# clamp in reachability.py; validated here so the MCP layer can reject bad
# input with a clean message before touching the database).
MAX_HOPS_FLOOR = 1
MAX_HOPS_CEILING = 12


def build_envelope(
    tool: str,
    summary: str,
    rows: list[dict[str, Any]],
    truncated: bool = False,
    extra_caveats: list[str] | None = None,
) -> dict[str, Any]:
    """Wrap tool output in the versioned response envelope.

    ``row_count`` is always ``len(rows)``. ``caveats`` always begins with the
    Java-only and soundness sentences, followed by any ``extra_caveats``.
    """
    caveats = [JAVA_ONLY_CAVEAT, SOUNDNESS_CAVEAT]
    if extra_caveats:
        caveats.extend(extra_caveats)
    return {
        "schema_version": TOOL_SCHEMA_VERSION,
        "tool": tool,
        "summary": summary,
        "row_count": len(rows),
        "truncated": bool(truncated),
        "caveats": caveats,
        "rows": rows,
    }


def namespaced_tool_name(base: str, namespace: str | None) -> str:
    """Prefix a tool name with an optional namespace (``<namespace>_<base>``).

    An empty or whitespace-only namespace returns ``base`` unchanged, so our
    server and, say, the Neo4j Labs ``mcp-neo4j-cypher`` server can coexist in
    one client config without tool-name collisions.
    """
    ns = (namespace or "").strip()
    return f"{ns}_{base}" if ns else base


def validate_max_hops(max_hops: Any) -> int:
    """Validate the var-length CALLS bound, returning a clamped int.

    Rejects bools and non-ints with a clear ``ValueError``; rejects values
    below ``MAX_HOPS_FLOOR`` (e.g. negative hops); clamps values above
    ``MAX_HOPS_CEILING`` down to the ceiling.
    """
    if isinstance(max_hops, bool) or not isinstance(max_hops, int):
        raise ValueError(f"max_hops must be an int, got {type(max_hops).__name__}: {max_hops!r}")
    if max_hops < MAX_HOPS_FLOOR:
        raise ValueError(f"max_hops must be >= {MAX_HOPS_FLOOR}, got {max_hops}")
    return min(MAX_HOPS_CEILING, max_hops)


def parse_gav(gav: str) -> tuple[str, str, str]:
    """Parse a ``group:artifact:version`` coordinate into its three parts.

    Raises ``ValueError`` when ``gav`` is not exactly three non-empty
    colon-separated segments.
    """
    if not isinstance(gav, str):
        raise ValueError(f"gav must be a string, got {type(gav).__name__}")
    parts = gav.split(":")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError(
            "gav must be 'group:artifact:version' (three non-empty parts), " f"got {gav!r}"
        )
    group_id, artifact_id, version = (part.strip() for part in parts)
    return group_id, artifact_id, version
