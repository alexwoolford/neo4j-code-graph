import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def test_calls_across_two_classes_in_one_file(tmp_path):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    java_dir = repo_root / "org" / "z"
    java_dir.mkdir(parents=True)
    file_path = java_dir / "Z.java"
    file_path.write_text(
        """
        package org.z;
        public class A { public void run(){ B.help(); this.self(); plain(); } public void self(){} }
        class B { public static void help(){} }
        """.strip(),
        encoding="utf-8",
    )

    result = extract_file_data(file_path, repo_root)
    a_methods = [m for m in result["methods"] if m.get("class_name") == "A" and m["name"] == "run"]
    assert a_methods
    calls = a_methods[0]["calls"]
    names = {c["method_name"] for c in calls}
    assert {"help", "self", "plain"}.issubset(names)
