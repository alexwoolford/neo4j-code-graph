#!/usr/bin/env python3
"""
Lightweight Java extractor using Tree-sitter.

Extracts imports, classes, interfaces, and method declarations with start/end
positions so downstream logic in code_analysis can remain unchanged.

Aura-compatible: pure Python and standard libraries only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Parser

try:
    # API expected for 0.20.x
    from tree_sitter_languages import get_language  # type: ignore
except Exception:  # pragma: no cover
    # Deferred import shim
    def get_language(name: str):  # type: ignore
        from tree_sitter_languages import get_language as _gl

        return _gl(name)


@dataclass
class JavaExtraction:
    package_name: str | None
    imports: list[dict[str, Any]]
    classes: list[dict[str, Any]]
    interfaces: list[dict[str, Any]]
    methods: list[dict[str, Any]]
    docs: list[dict[str, Any]]


def _node_text(source_bytes: bytes, node: Any) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _child_by_type(node: Any, type_name: str) -> Any | None:
    for child in getattr(node, "children", []) or []:
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
    imports: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    interfaces: list[dict[str, Any]] = []
    methods: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []

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
            base_path = _node_text(source_bytes, path_node).strip() if path_node else ""
            is_wildcard = any(grand.type == "asterisk" for grand in child.children)
            # detect static imports
            is_static = any(grand.type == "static" for grand in child.children)
            import_type = "external"
            if base_path.startswith("java.") or base_path.startswith("javax."):
                import_type = "standard"
            elif base_path.startswith("org.neo4j"):
                import_type = "internal"

            # Emit both base and wildcard variants when wildcard is present to match legacy expectations
            if is_wildcard:
                imports.append(
                    {
                        "import_path": base_path,
                        "is_static": is_static,
                        "is_wildcard": True,
                        "import_type": import_type,
                        "file": rel_path,
                    }
                )
            else:
                imports.append(
                    {
                        "import_path": base_path,
                        "is_static": is_static,
                        "is_wildcard": False,
                        "import_type": import_type,
                        "file": rel_path,
                    }
                )

    # Class, interface, and record declarations
    def _extract_return_type(mnode: Any) -> str:
        """Extract method return type from a method_declaration node."""
        # Find the identifier child to bound the search
        ident = _child_by_type(mnode, "identifier")
        ident_start = ident.start_byte if ident is not None else mnode.start_byte
        candidates = []
        for ch in mnode.children:
            if ch.end_byte <= ident_start and ch.type in (
                "void_type",
                "type",
                "type_identifier",
                "scoped_type_identifier",
                "integral_type",
                "floating_point_type",
                "boolean_type",
                "array_type",
            ):
                candidates.append(ch)
        if not candidates:
            return "void"
        node = candidates[-1]
        text = _node_text(source_bytes, node).strip()
        return text if text else "void"

    def walk(node: Any, ancestors: list[Any]) -> None:
        if node.type in ("class_declaration", "interface_declaration", "record_declaration"):
            identifier = _child_by_type(node, "identifier")
            name = _node_text(source_bytes, identifier) if identifier else ""
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            info: dict[str, Any] = {
                "name": name,
                "file": rel_path,
                "package": package_name,
                "line": start_line,
                "modifiers": [],
            }
            if node.type == "class_declaration":
                info.update({"type": "class", "estimated_lines": max(0, end_line - start_line)})
                classes.append(info)
                # Extract comment block immediately above class
                try:
                    lines = code.splitlines()
                    doc = _extract_comment_block_above(lines, start_line)
                    if doc:
                        docs.append(
                            {
                                "file": rel_path,
                                "language": "java",
                                "kind": doc.get("kind", "comment"),
                                "start_line": doc["start"],
                                "end_line": doc["end"],
                                "text": doc["text"],
                                "class_name": name,
                                "scope": "class",
                            }
                        )
                except Exception:
                    pass
            elif node.type == "interface_declaration":
                info.update({"type": "interface", "method_count": 0})
                interfaces.append(info)
            else:  # record_declaration
                info.update({"type": "record", "estimated_lines": max(0, end_line - start_line)})
                classes.append(info)

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

            # Compute lightweight cyclomatic complexity (McCabe approximation)
            # M = 1 + number of decision points inside the method
            def _compute_cyclomatic_for_method(mnode: Any) -> int:
                decision_kinds = {
                    "if_statement",
                    "while_statement",
                    "for_statement",
                    "enhanced_for_statement",
                    "do_statement",
                    "catch_clause",
                    "conditional_expression",
                }

                def _count(n: Any) -> int:
                    cnt = 0
                    # Count switch cases (exclude default)
                    if getattr(n, "type", None) == "switch_label":
                        try:
                            txt = _node_text(source_bytes, n).strip()
                            if txt.startswith("case"):
                                cnt += 1
                        except Exception:
                            pass
                    if getattr(n, "type", None) in decision_kinds:
                        cnt += 1
                    for ch in getattr(n, "children", []) or []:
                        cnt += _count(ch)
                    return cnt

                return _count(mnode)

            cyclomatic = 1 + _compute_cyclomatic_for_method(node)

            # Extract parameters
            params_list: list[dict[str, Any]] = []
            formal_params = _child_by_type(node, "formal_parameters")
            if formal_params is not None:
                # formal_parameters -> '(' parameter_list? ')'
                for ch in formal_params.children:
                    if ch.type in ("formal_parameter", "receiver_parameter", "spread_parameter"):
                        # Extract type
                        type_node = (
                            _child_by_type(ch, "type")
                            or _child_by_type(ch, "type_identifier")
                            or _child_by_type(ch, "scoped_type_identifier")
                            or _child_by_type(ch, "integral_type")
                            or _child_by_type(ch, "floating_point_type")
                            or _child_by_type(ch, "boolean_type")
                            or _child_by_type(ch, "array_type")
                        )
                        type_text = _node_text(source_bytes, type_node).strip() if type_node else ""
                        # Extract name (identifier possibly inside variable_declarator_id)
                        name_node = _child_by_type(ch, "identifier")
                        if name_node is None:
                            vdid = _child_by_type(ch, "variable_declarator_id")
                            if vdid is not None:
                                name_node = _child_by_type(vdid, "identifier")
                        name_text = _node_text(source_bytes, name_node).strip() if name_node else ""
                        params_list.append({"name": name_text, "type": type_text})

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
                    "return_type": _extract_return_type(node),
                    "parameters": params_list,
                    "code": "\n".join(method_code),
                    "cyclomatic_complexity": cyclomatic,
                    # Best-effort call extraction from AST (method_invocation nodes)
                    "calls": [],
                }
            )
            # Comment block immediately above method
            try:
                lines = code.splitlines()
                doc = _extract_comment_block_above(lines, start_line)
                if doc:
                    docs.append(
                        {
                            "file": rel_path,
                            "language": "java",
                            "kind": doc.get("kind", "comment"),
                            "start_line": doc["start"],
                            "end_line": doc["end"],
                            "text": doc["text"],
                            "method_signature": None,  # will be filled downstream when signature built
                            "method_name": method_name,
                            "class_name": owner_name,
                            "scope": "method",
                        }
                    )
            except Exception:
                pass
            # Populate calls by traversing the method subtree
            calls_list: list[dict[str, Any]] = []

            # Detect @Deprecated annotation on the method (lightweight)
            def _is_deprecated_annot(n: Any) -> bool:
                if getattr(n, "type", None) == "annotation":
                    try:
                        txt = _node_text(source_bytes, n).strip()
                        if "Deprecated" in txt:
                            return True
                    except Exception:
                        return False
                for ch in getattr(n, "children", []) or []:
                    if _is_deprecated_annot(ch):
                        return True
                return False

            deprecated_flag = _is_deprecated_annot(node)
            deprecated_message = None
            deprecated_since = None
            # If doc exists and contains @deprecated, capture message/since best-effort
            try:
                lines = code.splitlines()
                doc2 = _extract_comment_block_above(lines, start_line)
                if doc2 and "@deprecated" in doc2.get("text", "").lower():
                    deprecated_flag = True
                    text = doc2.get("text", "")
                    deprecated_message = text
                    # naive extraction of "since X" token
                    lower = text.lower()
                    idx = lower.find("since ")
                    if idx != -1:
                        frag = text[idx + len("since ") :].split("\n", 1)[0].strip()
                        deprecated_since = frag[:32]
            except Exception:
                pass

            def _walk_calls(n: Any) -> None:
                if n.type == "method_invocation":
                    # Extract invocation text and method name
                    inv_text = _node_text(source_bytes, n)
                    # Heuristic: qualifier.methodName(...)
                    # Extract method name as last identifier before '('
                    name_part = inv_text.split("(", 1)[0]
                    if "." in name_part:
                        qual, mname = name_part.rsplit(".", 1)
                        qualifier = qual.strip()
                    else:
                        mname = name_part.strip()
                        qualifier = ""
                    # Classify call type
                    if qualifier == "this":
                        call_type = "this"
                    elif qualifier == "super":
                        call_type = "super"
                    elif qualifier == "":
                        call_type = "same_class"
                    elif qualifier and qualifier[:1].isupper():
                        call_type = "static"
                    else:
                        call_type = "instance"
                    call_entry = {
                        "method_name": mname,
                        "target_class": None,
                        "call_type": call_type,
                        "qualifier": qualifier,
                    }
                    calls_list.append(call_entry)
                for ch in n.children:
                    _walk_calls(ch)

            _walk_calls(node)
            methods[-1]["calls"] = calls_list
            methods[-1]["deprecated"] = deprecated_flag
            if deprecated_message:
                methods[-1]["deprecated_message"] = deprecated_message
            if deprecated_since:
                methods[-1]["deprecated_since"] = deprecated_since

        for child in node.children:
            walk(child, ancestors + [node])

    walk(root, [])

    # Fix interface method counts
    for intf in interfaces:
        intf["method_count"] = sum(
            1 for m in methods if isinstance(m, dict) and m.get("class_name") == intf.get("name")
        )

    return JavaExtraction(
        package_name=package_name,
        imports=imports,
        classes=classes,
        interfaces=interfaces,
        methods=methods,
        docs=docs,
    )


def _extract_naive(code: str, rel_path: str) -> JavaExtraction:
    """Very small, regex-based Java extraction for CI environments without working
    tree-sitter wheels. Good enough for tiny fixture files used in live tests.
    """
    import re

    lines = code.splitlines()
    package_name: str | None = None
    imports: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    interfaces: list[dict[str, Any]] = []
    methods: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []

    # package
    for i, line in enumerate(lines, start=1):
        m = re.match(r"\s*package\s+([a-zA-Z0-9_.]+)\s*;", line)
        if m:
            package_name = m.group(1)
            break

    # imports
    for i, line in enumerate(lines, start=1):
        m = re.match(r"\s*import\s+(static\s+)?([a-zA-Z0-9_.]+)(\.\*)?\s*;", line)
        if not m:
            continue
        is_static = bool(m.group(1))
        base = m.group(2)
        is_wild = bool(m.group(3))
        import_type = "external"
        if base.startswith("java.") or base.startswith("javax."):
            import_type = "standard"
        elif base.startswith("org.neo4j"):
            import_type = "internal"
        imports.append(
            {
                "import_path": base,
                "is_static": is_static,
                "is_wildcard": is_wild,
                "import_type": import_type,
                "file": rel_path,
            }
        )

    # classes (very naive)
    for i, line in enumerate(lines, start=1):
        m = re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            classes.append(
                {
                    "name": m.group(1),
                    "file": rel_path,
                    "package": package_name,
                    "line": i,
                    "modifiers": [],
                    "type": "class",
                    "estimated_lines": max(0, len(lines) - i + 1),
                }
            )

    # methods (look for "+ returnType name(", accept void and simple types)
    method_pat = re.compile(
        r"\b(?:public|private|protected|static|final|\s)*\b([A-Za-z_][A-Za-z0-9_<>\[\]]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
    )
    for i, line in enumerate(lines, start=1):
        for mm in method_pat.finditer(line):
            ret, name = mm.groups()
            # Skip constructor-like where return type equals enclosing class will be handled downstream
            methods.append(
                {
                    "name": name,
                    "class_name": classes[0]["name"] if classes else None,
                    "containing_type": "class" if classes else None,
                    "line": i,
                    "estimated_lines": 1,
                    "modifiers": [],
                    "is_static": False,
                    "is_abstract": False,
                    "is_final": False,
                    "is_private": False,
                    "is_public": False,
                    "return_type": ret or "void",
                    "parameters": [],
                    "code": line,
                    "calls": [],
                }
            )
            # naive doc above method
            try:
                doc = _extract_comment_block_above(lines, i)
                if doc:
                    docs.append(
                        {
                            "file": rel_path,
                            "language": "java",
                            "kind": doc.get("kind", "comment"),
                            "start_line": doc["start"],
                            "end_line": doc["end"],
                            "text": doc["text"],
                            "method_name": name,
                            "class_name": classes[0]["name"] if classes else None,
                            "scope": "method",
                        }
                    )
            except Exception:
                pass

    # fix interface method counts
    for intf in interfaces:
        intf["method_count"] = sum(1 for m in methods if m.get("class_name") == intf["name"])

    return JavaExtraction(
        package_name=package_name,
        imports=imports,
        classes=classes,
        interfaces=interfaces,
        methods=methods,
        docs=docs,
    )


def extract_file_data(java_file: Path, project_root: Path) -> dict[str, Any]:
    """
    Heuristic extractor API compatible with tests expecting extract_file_data.
    Returns a dict with counts and methods/interfaces/classes similar to javalang path.
    """
    # Ensure absolute path to avoid current-working-dir surprises
    abs_path = java_file if java_file.is_absolute() else (project_root / java_file)
    code = abs_path.read_text(encoding="utf-8")
    rel_path = str(abs_path.relative_to(project_root))
    # Prefer Tree-sitter; fall back to a naive extractor if unavailable/miscompiled
    try:
        extraction = extract_with_treesitter(code, rel_path)
    except Exception:
        extraction = _extract_naive(code, rel_path)

    # Ensure method entries carry required fields for downstream writers
    def _build_signature(
        pkg: str | None,
        cls: str | None,
        name: str,
        params: list[dict[str, Any]] | None,
        ret: str | None,
    ) -> str:
        pkg_prefix = f"{pkg}." if pkg else ""
        owner = cls or ""
        param_types = []
        if params:
            for p in params:
                t = p.get("type") if isinstance(p, dict) else None
                if t is not None:
                    param_types.append(str(t))
        params_sig = ",".join(param_types)
        ret_type = ret or "void"
        return f"{pkg_prefix}{owner}#{name}({params_sig}):{ret_type}"

    for m in extraction.methods:
        # File path is required downstream
        m.setdefault("file", rel_path)
        # Best-effort signature for uniqueness/merge
        try:
            m.setdefault(
                "method_signature",
                _build_signature(
                    extraction.package_name,
                    m.get("class_name"),
                    m.get("name", ""),
                    m.get("parameters"),
                    m.get("return_type"),
                ),
            )
        except Exception:
            # Fallback to minimal signature
            name = m.get("name", "")
            m.setdefault("method_signature", f"{m.get('class_name') or ''}#{name}():void")
    # Attach method signatures to docs that reference method/class names
    for d in extraction.docs:
        if isinstance(d, dict) and d.get("method_name"):
            # Find matching method by name and class
            for m in extraction.methods:
                if not isinstance(m, dict):
                    continue
                if m.get("name") == d.get("method_name") and m.get("class_name") == d.get(
                    "class_name"
                ):
                    d["method_signature"] = m.get("method_signature")
                    break

    return {
        "path": rel_path,
        "code": code,
        "imports": extraction.imports,
        "classes": extraction.classes,
        "interfaces": extraction.interfaces,
        "methods": extraction.methods,
        "docs": extraction.docs,
        "language": "java",
        "ecosystem": "maven",
        "total_lines": len(code.splitlines()),
        "code_lines": len([line for line in code.splitlines() if line.strip()]),
        "method_count": len(extraction.methods),
        "class_count": len(extraction.classes),
        "interface_count": len(extraction.interfaces),
    }


def _extract_comment_block_above(lines: list[str], start_line: int) -> dict[str, Any] | None:
    """Heuristic: return contiguous comment block immediately above start_line (1-based).
    Supports // line comments and /* ... */ blocks. Returns dict with start,end,text.
    """
    idx = start_line - 2
    if idx < 0:
        return None
    # Skip single blank line directly above
    if idx >= 0 and not lines[idx].strip():
        idx -= 1
    if idx < 0:
        return None
    # Block comment ending at idx (/** javadoc */ or /* block */)
    if lines[idx].strip().endswith("*/"):
        end = idx + 1
        # Find start of block
        j = idx
        while j >= 0:
            if "/*" in lines[j]:
                start = j + 1
                break
            j -= 1
        else:
            return None
        raw = lines[start - 1 : end]
        text = _clean_comment_text(raw)
        kind = "javadoc" if any("/**" in ln for ln in raw) else "block_comment"
        return {"start": start, "end": end, "text": text, "kind": kind}
    # Line comments //
    if lines[idx].lstrip().startswith("//"):
        end = idx + 1
        j = idx
        while j >= 0 and lines[j].lstrip().startswith("//"):
            j -= 1
        start = j + 2
        raw = lines[start - 1 : end]
        text = _clean_comment_text(raw)
        return {"start": start, "end": end, "text": text, "kind": "line_comment"}
    return None


def _clean_comment_text(raw_lines: list[str]) -> str:
    buf: list[str] = []
    for ln in raw_lines:
        s = ln.strip()
        if s.startswith("/*"):
            s = s[2:]
        if s.endswith("*/"):
            s = s[:-2]
        s = s.lstrip("*")
        if s.startswith("//"):
            s = s[2:]
        buf.append(s.strip())
    text = "\n".join(buf).strip()
    if len(text) > 1000:
        text = text[:1000]
    return text
