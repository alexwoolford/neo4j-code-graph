#!/usr/bin/env python3
from pathlib import Path

import pytest


@pytest.mark.live
def test_treesitter_fallback_extracts_required_fields(tmp_path: Path):
    # Create a minimal Java file that Tree-sitter can parse even if javalang fails upstream
    src = tmp_path / "src/main/java/com/example/Hello.java"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(
        """
        package com.example;
        public class Hello {
            public void greet() { System.out.println("hi"); }
        }
        """.strip()
    )

    # Call the fallback extractor directly
    from src.analysis.java_treesitter import extract_file_data  # type: ignore

    data = extract_file_data(src, tmp_path)
    assert data["path"].endswith("com/example/Hello.java")
    assert data["language"] == "java"
    assert data["ecosystem"] == "maven"
    # Ensure required method fields exist for writer
    methods = data["methods"]
    assert methods
    for m in methods:
        assert "file" in m and m["file"].endswith("com/example/Hello.java")
        assert isinstance(m.get("method_signature"), str) and "#" in m["method_signature"]
