from __future__ import annotations

import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


add_src_to_path()

try:
    from analysis.java_treesitter import extract_file_data as ts_extract  # noqa: E402
except Exception:
    ts_extract = None


def require_ts():
    if ts_extract is None:
        import pytest

        pytest.skip("tree-sitter not available")


def test_lambda_and_method_refs(tmp_path):
    require_ts()
    src_dir = tmp_path / "pkg"
    src_dir.mkdir(parents=True)
    java_file = src_dir / "Demo.java"
    java_file.write_text(
        """
        package pkg;
        import java.util.*;
        public class Demo {
          public void run(){
            List<String> xs = Arrays.asList("a","b");
            xs.forEach(s -> System.out.println(s));
            xs.forEach(System.out::println);
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    data = ts_extract(java_file, tmp_path)
    # Basic sanity: one class, one method
    assert data["class_count"] >= 1
    assert any(m.get("name") == "run" for m in data.get("methods", []))
