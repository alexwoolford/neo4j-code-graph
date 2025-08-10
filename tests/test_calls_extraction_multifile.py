import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def test_calls_across_two_files(tmp_path):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    a_dir = repo_root / "pkg"
    a_dir.mkdir(parents=True)
    a_file = a_dir / "A.java"
    b_file = a_dir / "B.java"

    a_file.write_text(
        """
        package pkg;
        public class A { public void run(){ B.help(); } }
        """.strip(),
        encoding="utf-8",
    )
    b_file.write_text(
        """
        package pkg;
        public class B { public static void help(){} }
        """.strip(),
        encoding="utf-8",
    )

    a_data = extract_file_data(a_file, repo_root)
    b_data = extract_file_data(b_file, repo_root)

    methods = a_data["methods"] + b_data["methods"]
    a_run = [m for m in methods if m.get("class_name") == "A" and m["name"] == "run"]
    assert a_run
    calls = a_run[0]["calls"]
    assert any(c["method_name"] == "help" for c in calls)
