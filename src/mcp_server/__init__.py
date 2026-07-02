"""Curated MCP server exposing code-graph risk queries as typed tools.

See :mod:`mcp_server.server` for the FastMCP app and :mod:`mcp_server.contracts`
for the response-envelope contract. All Cypher lives in
``src/security/reachability.py`` (the single source of truth); this package is
Cypher-free.
"""

from mcp_server.contracts import TOOL_SCHEMA_VERSION

__all__ = ["TOOL_SCHEMA_VERSION"]
