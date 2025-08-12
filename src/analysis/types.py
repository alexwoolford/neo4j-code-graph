"""
TypedDicts for analysis data structures.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class ImportInfo(TypedDict):
    import_path: str
    is_static: bool
    is_wildcard: bool
    import_type: str
    file: str


class MethodParameter(TypedDict):
    name: str
    type: str | None


class MethodInfo(TypedDict):
    name: str
    file: str
    line: int | None
    code: str
    estimated_lines: NotRequired[int]
    class_name: NotRequired[str]
    containing_type: NotRequired[str]
    parameters: list[MethodParameter]
    modifiers: list[str]
    is_static: bool
    is_abstract: bool
    is_final: bool
    is_private: bool
    is_public: bool
    return_type: str
    calls: list[dict[str, str | None]]
    method_signature: NotRequired[str]


class ClassInfo(TypedDict):
    name: str
    type: str
    file: str
    package: str | None
    line: int | None
    modifiers: list[str]
    extends: str | None
    implements: list[str]
    is_abstract: bool
    is_final: bool
    estimated_lines: NotRequired[int]


class InterfaceInfo(TypedDict):
    name: str
    type: str
    file: str
    package: str | None
    line: int | None
    modifiers: list[str]
    extends: list[str]
    method_count: NotRequired[int]


class FileData(TypedDict):
    path: str
    code: str
    methods: list[MethodInfo]
    classes: list[ClassInfo]
    interfaces: list[InterfaceInfo]
    imports: list[ImportInfo]
    language: str
    ecosystem: str
    total_lines: int
    code_lines: int
    method_count: int
    class_count: int
    interface_count: int
