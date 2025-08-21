#!/usr/bin/env python3
"""
Generate detailed node property documentation from a live Neo4j database
and write it into docs/modules/ROOT/pages/graph-model.adoc.

Usage:
  python scripts/generate_graph_model_properties.py [--uri ... --username ... --password ... --database ...]

Connection defaults are read from .env via get_neo4j_config(); explicit CLI args override.

This script uses CALL db.schema.nodeTypeProperties() to enumerate labels and properties,
and enriches them with human-readable descriptions based on this project's schema.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from neo4j import READ_ACCESS, Driver

# Reuse shared connection helpers and config discovery
try:
    from constants import EMBEDDING_PROPERTY
    from utils.common import add_common_args, create_neo4j_driver
except Exception:  # repo-relative execution
    from src.constants import EMBEDDING_PROPERTY  # type: ignore
    from src.utils.common import add_common_args, create_neo4j_driver  # type: ignore


TARGET_DOC = Path("docs/modules/ROOT/partials/graph-model-content.adoc")


logger = logging.getLogger(__name__)


# Canonical/known properties by label for offline fallback and descriptions
KNOWN_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "File": {
        "path": "Repository-relative file path (unique).",
        "name": "File name (basename).",
        EMBEDDING_PROPERTY: "Vector embedding for file content (if generated).",
        "embedding_type": "Embedding model tag used to produce the vector.",
        "language": "Primary language detected for the file (e.g., java).",
        "ecosystem": "Build ecosystem (e.g., maven).",
        "total_lines": "Total number of lines in the file.",
        "code_lines": "Non-empty, non-comment lines of code (approximate).",
        "method_count": "Number of method declarations in this file.",
        "class_count": "Number of class declarations in this file.",
        "interface_count": "Number of interface declarations in this file.",
    },
    "FileVer": {
        "sha": "Commit SHA that produced this file version (part of natural key).",
        "path": "File path for this version (part of natural key).",
    },
    "Method": {
        "method_signature": "Stable unique signature for the method (unique).",
        "id": "Internal identifier mirroring the signature for convenience.",
        "name": "Method name.",
        "class_name": "Declaring class name (if applicable).",
        "containing_type": "Declaring type (class or interface) name when known.",
        "file": "Repository-relative file path containing the method.",
        "line": "Line number where the method starts.",
        "estimated_lines": "Approximate number of source lines in the method.",
        "is_static": "True if the method is static.",
        "is_abstract": "True if the method is abstract.",
        "is_final": "True if the method is final.",
        "is_private": "True if the method is private.",
        "is_public": "True if the method is public.",
        "return_type": "Declared return type.",
        "modifiers": "List of Java modifiers present on the method.",
        EMBEDDING_PROPERTY: "Vector embedding for method body (if generated).",
        "embedding_type": "Embedding model tag used to produce the vector.",
        # Derived metrics (optional)
        "pagerank_score": "PageRank centrality score on the call graph.",
        "betweenness_score": "Betweenness centrality score on the call graph.",
        "in_degree": "Number of distinct incoming CALLS.",
        "out_degree": "Number of distinct outgoing CALLS.",
        "total_degree": "Sum of in_degree and out_degree.",
        "similarityCommunity": "Community id from similarity clustering (Louvain).",
        "hits_auth": "HITS authority score (if computed).",
        "hits_hub": "HITS hub score (if computed).",
    },
    "Class": {
        "name": "Class name (unique with file).",
        "file": "Repository-relative file path declaring the class.",
        "line": "Line number where the class starts.",
        "estimated_lines": "Approximate number of lines spanned by the class.",
        "is_abstract": "True if the class is abstract.",
        "is_final": "True if the class is final.",
        "modifiers": "List of Java modifiers present on the class.",
    },
    "Interface": {
        "name": "Interface name (unique with file).",
        "file": "Repository-relative file path declaring the interface.",
        "line": "Line number where the interface starts.",
        "method_count": "Number of declared methods in the interface.",
        "modifiers": "List of Java modifiers present on the interface.",
    },
    "Import": {
        "import_path": "Imported type or package path (unique).",
        "is_static": "True for static imports.",
        "is_wildcard": "True if the import uses wildcard syntax (e.g., *).",
        "import_type": "One of internal|external (derived from analysis).",
    },
    "ExternalDependency": {
        "package": "Base package or coordinate identifying the dependency (unique).",
        "language": "Programming language associated with the dependency graph.",
        "ecosystem": "Dependency ecosystem (e.g., maven).",
        "version": "Resolved version when available.",
        "group_id": "Group identifier (Maven).",
        "artifact_id": "Artifact identifier (Maven).",
    },
    "Commit": {
        "sha": "Commit SHA (unique).",
        "date": "Commit timestamp (datetime).",
        "message": "Commit message.",
    },
    "Developer": {
        "email": "Author email (unique).",
        "name": "Author display name.",
    },
    "CVE": {
        "id": "CVE identifier (unique).",
        "cvss_score": "CVSS base score (0-10).",
        "severity": "Severity classification (e.g., CRITICAL, HIGH).",
        "description": "Short description from NVD.",
        "published": "Published date/time from NVD.",
    },
    "Directory": {
        "path": "Directory path relative to repository root (unique).",
    },
}


@dataclass(frozen=True)
class PropertyDoc:
    name: str
    types: tuple[str, ...]
    description: str


def _infer_description(label: str, prop: str) -> str:
    """Best-effort descriptions per known schema. Fallback is generic."""
    descriptions = KNOWN_DESCRIPTIONS

    label_map = descriptions.get(label, {})
    if prop in label_map:
        return label_map[prop]
    # Fallbacks for common dynamic/derived properties
    if prop.startswith("embedding_"):
        return "Vector embedding written by the embedding stage."
    return "Derived or auxiliary property written by specific stages."


def _labels_order() -> list[str]:
    # Keep a stable, curated order in docs
    return [
        "File",
        "FileVer",
        "Method",
        "Class",
        "Interface",
        "Import",
        "ExternalDependency",
        "Commit",
        "Developer",
        "CVE",
        "Directory",
    ]


def _collect_properties(
    driver: Driver, database: str | None
) -> Mapping[str, list[tuple[str, tuple[str, ...]]]]:
    """Return mapping: label -> list of (propertyName, propertyTypes)."""
    query = "CALL db.schema.nodeTypeProperties()"
    props_by_label: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
        for rec in session.run(query):
            labels: list[str] = rec.get("nodeLabels", [])
            prop: str = rec.get("propertyName")
            types: list[str] = rec.get("propertyTypes", [])
            if not prop or not labels:
                continue
            for label in labels:
                props_by_label[label][prop].update(types or [])

    # Convert to ordered lists
    out: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for label, prop_map in props_by_label.items():
        items: list[tuple[str, tuple[str, ...]]] = sorted(
            (p, tuple(sorted(ts)) if ts else tuple()) for p, ts in prop_map.items()
        )
        out[label] = items
    return out


def _collect_properties_offline() -> Mapping[str, list[tuple[str, tuple[str, ...]]]]:
    """Fallback: use known descriptions as the source of property names/types."""
    out: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for label in _labels_order():
        props = KNOWN_DESCRIPTIONS.get(label, {})
        if not props:
            continue
        items: list[tuple[str, tuple[str, ...]]] = [(p, tuple()) for p in sorted(props.keys())]
        out[label] = items
    return out


def _render_asciidoc(collected: Mapping[str, list[tuple[str, tuple[str, ...]]]]) -> str:
    lines: list[str] = []
    lines.append("\n== Node properties (generated)\n")
    lines.append(
        "These property lists are generated from the live database via `db.schema.nodeTypeProperties()` and annotated with descriptions."
    )
    lines.append("")
    for label in _labels_order():
        if label not in collected:
            continue
        lines.append(f"=== {label}")
        for prop, types in collected[label]:
            desc = _infer_description(label, prop)
            type_hint = f" ({', '.join(types)})" if types else ""
            lines.append(f"- `{prop}`{type_hint}: {desc}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _update_docs(doc_path: Path, new_section: str) -> None:
    original = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
    marker_start = "// BEGIN GENERATED: NODE_PROPERTIES"
    marker_end = "// END GENERATED: NODE_PROPERTIES"
    generated_block = f"{marker_start}\n{new_section}{marker_end}\n"

    if marker_start in original and marker_end in original:
        # Replace existing generated section
        prefix = original.split(marker_start, 1)[0]
        suffix = original.split(marker_end, 1)[1]
        updated = prefix + generated_block + suffix
    else:
        # Append to the end to avoid disrupting curated content
        updated = original.rstrip() + "\n\n" + generated_block

    doc_path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate graph model property docs from Neo4j")
    add_common_args(parser)
    args = parser.parse_args()

    # Try live collection; if unavailable, fall back to offline known schema
    try:
        with create_neo4j_driver(args.uri, args.username, args.password) as driver:
            collected = _collect_properties(driver, args.database)
    except Exception as e:
        logger.warning(
            "Neo4j connection unavailable; generating docs from known schema only: %s", e
        )
        collected = _collect_properties_offline()

    section = _render_asciidoc(collected)
    _update_docs(TARGET_DOC, section)

    print(f"Updated {TARGET_DOC} with generated node property documentation.")


if __name__ == "__main__":
    main()
