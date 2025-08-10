import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def test_extract_simple_class_and_method(tmp_path):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    java_dir = repo_root / "com" / "example"
    java_dir.mkdir(parents=True)
    file_path = java_dir / "Hello.java"
    file_path.write_text(
        """
        package com.example;
        public class Hello {
            public int add(int a, int b) {
                return a + b;
            }
        }
        """.strip(),
        encoding="utf-8",
    )

    result = extract_file_data(file_path, repo_root)
    assert result is not None
    assert result["path"].endswith("com/example/Hello.java")
    assert result["language"] == "java"
    assert any(c["name"] == "Hello" for c in result["classes"])
    method_names = {m["name"] for m in result["methods"]}
    assert "add" in method_names


def test_extract_interface_with_method(tmp_path):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    java_dir = repo_root / "org" / "demo"
    java_dir.mkdir(parents=True)
    file_path = java_dir / "Api.java"
    file_path.write_text(
        """
        package org.demo;
        public interface Api {
            String greet(String name);
        }
        """.strip(),
        encoding="utf-8",
    )

    result = extract_file_data(file_path, repo_root)
    assert result is not None
    assert any(i["name"] == "Api" for i in result["interfaces"])
    assert any(m["name"] == "greet" for m in result["methods"])
