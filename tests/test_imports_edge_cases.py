import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def test_static_and_wildcard_imports(tmp_path):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    java_dir = repo_root / "a" / "b"
    java_dir.mkdir(parents=True)
    file_path = java_dir / "X.java"
    file_path.write_text(
        """
        package a.b;
        import static java.util.Collections.emptyList;
        import com.acme.*;
        public class X {}
        """.strip(),
        encoding="utf-8",
    )

    result = extract_file_data(file_path, repo_root)
    imps = {i["import_path"]: i for i in result["imports"]}

    assert "java.util.Collections.emptyList" in imps
    assert imps["java.util.Collections.emptyList"]["is_static"] is True

    # javalang represents wildcard imports by base path + is_wildcard flag
    assert "com.acme" in imps
    assert imps["com.acme"]["is_wildcard"] is True
    assert imps["com.acme"]["import_type"] == "external"
