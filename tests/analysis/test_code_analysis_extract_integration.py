#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_extract_file_data_from_small_java(tmp_path: Path):
    from src.analysis.code_analysis import extract_file_data

    repo = tmp_path / "repo"
    java = repo / "src" / "main" / "java" / "p" / "q" / "A.java"
    _write(
        java,
        """
        package p.q;

        import java.util.List;
        import org.neo4j.graphdb.Node;
        import com.example.lib.Util;

        public interface I extends AutoCloseable {
            void run();
        }

        public class A implements Runnable {
            public void a(int x) {
                Object obj = new Object();
                this.helper();
                Helper.staticCall();
                obj.instanceCall();
                super.toString();
                method();
            }

            private void helper() {}
        }
        """,
    )

    fd = extract_file_data(java, repo)

    # Path is relative to repo
    assert fd["path"].endswith("p/q/A.java")

    # Language/ecosystem tagging present
    assert fd["language"] == "java"
    assert fd["ecosystem"] == "maven"

    # Imports classified correctly
    kinds = {(i["import_path"], i["import_type"]) for i in fd["imports"]}
    assert ("java.util.List", "standard") in kinds
    assert ("org.neo4j.graphdb.Node", "internal") in kinds
    assert ("com.example.lib.Util", "external") in kinds

    # Classes and interfaces discovered
    class_names = {c["name"] for c in fd["classes"]}
    iface_names = {i["name"] for i in fd["interfaces"]}
    assert "A" in class_names
    assert "I" in iface_names

    # Methods extracted with signatures and metadata
    methods = {m["name"]: m for m in fd["methods"]}
    assert "a" in methods and "helper" in methods
    assert methods["a"]["method_signature"].startswith("p.q.A#a(")
    assert methods["a"]["containing_type"] == "class"
    assert methods["a"]["class_name"] == "A"

    # Calls include same_class/this/static/instance/super variants when available
    calls = methods["a"].get("calls")
    if calls is not None:
        call_types = {c["call_type"] for c in calls}
        assert {"same_class", "this", "static", "instance", "super"}.issubset(call_types)

    # Basic line metrics present
    assert isinstance(methods["a"]["estimated_lines"], int)
    assert isinstance(fd["classes"][0].get("estimated_lines", 0), int)
