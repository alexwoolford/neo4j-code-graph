import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def test_import_extraction(tmp_path):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    java_dir = repo_root / "com" / "example"
    java_dir.mkdir(parents=True)
    file_path = java_dir / "Demo.java"
    file_path.write_text(
        """
        package com.example;
        import java.util.List;
        import org.neo4j.graphdb.GraphDatabaseService;
        import com.acme.lib.Util;
        public class Demo {}
        """.strip(),
        encoding="utf-8",
    )

    result = extract_file_data(file_path, repo_root)
    imports = {i["import_path"]: i["import_type"] for i in result["imports"]}
    assert imports["java.util.List"] == "standard"
    assert imports["org.neo4j.graphdb.GraphDatabaseService"] == "internal"
    assert imports["com.acme.lib.Util"] == "external"


def test_method_file_relationship_shape(tmp_path):
    add_src_to_path()
    from analysis.code_analysis import extract_file_data

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    java_dir = repo_root / "com" / "demo"
    java_dir.mkdir(parents=True)
    file_path = java_dir / "Demo.java"
    file_path.write_text(
        """
        package com.demo;
        public class Demo {
            public void run() {
                Helper.help();
            }
        }
        class Helper {
            public static void help() {}
        }
        """.strip(),
        encoding="utf-8",
    )

    result = extract_file_data(file_path, repo_root)
    # Ensure each method has file path and line required to later form relationships
    assert result["methods"]
    for m in result["methods"]:
        assert m["file"].endswith("com/demo/Demo.java")
        assert isinstance(m["line"], int) and m["line"] > 0
