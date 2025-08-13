#!/usr/bin/env python3
"""
Lightweight Java extractor using Tree-sitter as a fallback when javalang fails.

Extracts imports, classes, interfaces, and method declarations with start/end
positions so downstream logic in code_analysis can remain unchanged.

Aura-compatible: pure Python and standard libraries only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Parser
from tree_sitter_languages import get_language


@dataclass
class JavaExtraction:
    package_name: str | None
    imports: list[dict]
    classes: list[dict]
    interfaces: list[dict]
    methods: list[dict]


def _node_text(source_bytes: bytes, node) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _child_by_type(node, type_name: str):
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def extract_with_treesitter(code: str, rel_path: str) -> JavaExtraction:
    """
    Parse Java source using Tree-sitter and return structured artifacts.
    """
    lang = get_language("java")
    parser = Parser()
    parser.set_language(lang)
    tree = parser.parse(code.encode("utf-8", errors="ignore"))
    root = tree.root_node
    source_bytes = code.encode("utf-8", errors="ignore")

    package_name: str | None = None
    imports: list[dict] = []
    classes: list[dict] = []
    interfaces: list[dict] = []
    methods: list[dict] = []

    # Collect package name
    for child in root.children:
        if child.type == "package_declaration":
            # e.g., package a.b.c;
            name_node = _child_by_type(child, "scoped_identifier") or _child_by_type(
                child, "identifier"
            )
            if name_node is not None:
                package_name = _node_text(source_bytes, name_node).strip()
            break

    # Imports
    for child in root.children:
        if child.type == "import_declaration":
            # import a.b.c.*;
            path_node = _child_by_type(child, "scoped_identifier") or _child_by_type(
                child, "identifier"
            )
            import_path = _node_text(source_bytes, path_node).strip() if path_node else ""
            if child.child_count and child.children[-1].type == "asterisk":
                import_path = f"{import_path}.*"

            import_type = "external"
            if import_path.startswith("java.") or import_path.startswith("javax."):
                import_type = "standard"
            elif import_path.startswith("org.neo4j"):
                import_type = "internal"

            imports.append(
                {
                    "import_path": import_path,
                    "is_static": False,  # Tree-sitter differentiation optional here
                    "is_wildcard": import_path.endswith(".*"),
                    "import_type": import_type,
                    "file": rel_path,
                }
            )

    # Class and interface declarations
    def walk(node, ancestors: list):
        if node.type in ("class_declaration", "interface_declaration"):
            identifier = _child_by_type(node, "identifier")
            name = _node_text(source_bytes, identifier) if identifier else ""
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            info = {
                "name": name,
                "file": rel_path,
                "package": package_name,
                "line": start_line,
                "modifiers": [],
            }
            if node.type == "class_declaration":
                info.update({"type": "class", "estimated_lines": max(0, end_line - start_line)})
                classes.append(info)
            else:
                info.update({"type": "interface", "method_count": 0})
                interfaces.append(info)

        if node.type == "method_declaration":
            # Find owning type name by walking ancestors
            owner_name = None
            owner_type = None
            for anc in reversed(ancestors):
                if anc.type == "class_declaration":
                    ident = _child_by_type(anc, "identifier")
                    owner_name = _node_text(source_bytes, ident) if ident else None
                    owner_type = "class"
                    break
                if anc.type == "interface_declaration":
                    ident = _child_by_type(anc, "identifier")
                    owner_name = _node_text(source_bytes, ident) if ident else None
                    owner_type = "interface"
                    break

            ident = _child_by_type(node, "identifier")
            method_name = _node_text(source_bytes, ident) if ident else ""
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            method_code = code.splitlines()[start_line - 1 : end_line]

            methods.append(
                {
                    "name": method_name,
                    "class_name": owner_name,
                    "containing_type": owner_type,
                    "line": start_line,
                    "estimated_lines": max(1, end_line - start_line + 1),
                    "modifiers": [],
                    "is_static": False,
                    "is_abstract": False,
                    "is_final": False,
                    "is_private": False,
                    "is_public": False,
                    "return_type": "void",  # Simplified; refined by downstream if needed
                    "parameters": [],
                    "code": "\n".join(method_code),
                }
            )

        for child in node.children:
            walk(child, ancestors + [node])

    walk(root, [])

    # Fix interface method counts
    for intf in interfaces:
        intf["method_count"] = sum(1 for m in methods if m.get("class_name") == intf["name"])

    return JavaExtraction(
        package_name=package_name,
        imports=imports,
        classes=classes,
        interfaces=interfaces,
        methods=methods,
    )


def extract_file_data(java_file: Path, project_root: Path) -> dict:
    """
    Heuristic extractor API compatible with tests expecting extract_file_data.
    Returns a dict with counts and methods/interfaces/classes similar to javalang path.
    """
    code = java_file.read_text(encoding="utf-8")
    rel_path = str(java_file.relative_to(project_root))
    extraction = extract_with_treesitter(code, rel_path)
    return {
        "path": rel_path,
        "code": code,
        "imports": extraction.imports,
        "classes": extraction.classes,
        "interfaces": extraction.interfaces,
        "methods": extraction.methods,
        "language": "java",
        "ecosystem": "maven",
        "total_lines": len(code.splitlines()),
        "code_lines": len([line for line in code.splitlines() if line.strip()]),
        "method_count": len(extraction.methods),
        "class_count": len(extraction.classes),
        "interface_count": len(extraction.interfaces),
    }
