from __future__ import annotations

import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
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


def test_records_and_enums_and_inner_classes(tmp_path):
    require_ts()
    src_dir = tmp_path / "pkg"
    src_dir.mkdir(parents=True)
    java_file = src_dir / "Demo.java"
    java_file.write_text(
        """
        package pkg;
        public enum Role { ADMIN, USER }
        public class Outer {
          public class Inner { public void x(){} }
        }
        public record Point(int x, int y) {}
        """.strip(),
        encoding="utf-8",
    )
    assert ts_extract is not None
    data = ts_extract(java_file, tmp_path)
    # Ensure we discovered at least one class/interface/enum/record token
    assert data["class_count"] + data["interface_count"] >= 1
