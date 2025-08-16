#!/usr/bin/env python3
"""
Generate a DAG diagram for the Prefect flow and write it to the docs assets.

We prefer to use Prefect's own visualization if available. If that's not
available in the installed Prefect version, we fall back to a static graph that
matches the current flow defined in `src/pipeline/prefect_flow.py`.

Output: docs/modules/ROOT/assets/images/prefect-dag.png
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_output_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _try_prefect_visualize() -> bool:
    """Try to render the flow using Prefect's visualization utilities.

    Returns True on success, False to fall back.
    """
    try:
        # Import flow without executing as a script
        from src.pipeline.prefect_flow import code_graph_flow  # type: ignore

        try:
            # Prefect 2 provided .visualize(); Prefect 3 may offer similar API.
            # We attempt a best-effort call. If it fails, fall back.
            gv = code_graph_flow.visualize()  # type: ignore[attr-defined]
            # Force portrait orientation
            try:
                gv.graph_attr.update(rankdir="TB")  # type: ignore[attr-defined]
            except Exception:
                pass
            out = Path("docs/modules/ROOT/assets/images/prefect-dag")
            _ensure_output_dir(out)
            gv.format = "png"
            gv.render(filename=str(out), cleanup=True)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _render_static_graph() -> None:
    from graphviz import Digraph

    out = Path("docs/modules/ROOT/assets/images/prefect-dag")
    _ensure_output_dir(out)

    g = Digraph("neo4j-code-graph-dag", format="png")
    # Portrait orientation (Top-to-Bottom)
    g.attr(rankdir="TB", fontsize="10")
    g.attr("node", shape="box", style="rounded,filled", fillcolor="#f7f7f7")

    # Nodes
    nodes = [
        ("setup_schema", "Setup Schema"),
        ("cleanup", "Cleanup Previous Run"),
        ("clone_repo", "Clone Repo"),
        ("extract_code", "Extract Code Structure"),
        ("embed_files", "Embed Files"),
        ("embed_methods", "Embed Methods"),
        ("write_graph", "Write to Neo4j"),
        ("cleanup_artifacts", "Cleanup Artifacts"),
        ("git_history", "Load Git History"),
        ("coupling", "Create CO_CHANGED"),
        ("similarity", "Similarity (kNN)"),
        ("louvain", "Communities (Louvain)"),
        ("centrality", "Centrality"),
        ("cve", "CVE Analysis (optional)"),
    ]

    for nid, label in nodes:
        g.node(nid, label)

    # Edges reflect current execution order and explicit waits in the flow
    edges = [
        ("setup_schema", "cleanup"),
        ("cleanup", "clone_repo"),
        ("clone_repo", "extract_code"),
        ("extract_code", "embed_files"),
        ("embed_files", "embed_methods"),
        ("embed_methods", "write_graph"),
        ("write_graph", "cleanup_artifacts"),
        ("write_graph", "git_history"),
        ("git_history", "coupling"),
        ("coupling", "similarity"),
        ("similarity", "louvain"),
        ("louvain", "centrality"),
        ("centrality", "cve"),
    ]

    for a, b in edges:
        g.edge(a, b)

    g.render(filename=str(out), cleanup=True)


def main() -> int:
    if _try_prefect_visualize():
        return 0
    try:
        _render_static_graph()
        return 0
    except Exception as e:
        print(f"Failed to render DAG: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
