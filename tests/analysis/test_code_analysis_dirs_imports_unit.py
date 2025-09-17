#!/usr/bin/env python3

from __future__ import annotations


class _FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def run(self, q: str, **params):
        self.calls.append((" ".join(q.split()), params))

        class _R:
            @staticmethod
            def consume():
                return None

        return _R()


def test_create_directories_creates_root_and_relationships():
    from src.analysis.code_analysis import create_directories

    files_data = [
        {"path": "src/a/b/C.java"},
        {"path": "src/a/D.java"},
        {"path": "E.java"},  # root file
    ]
    s = _FakeSession()
    create_directories(s, files_data)
    joined = "\n".join(q for q, _ in s.calls)
    # Directory nodes and relationships queries should be invoked
    assert "UNWIND $directories AS dir_path MERGE (:Directory {path: dir_path})" in joined
    assert (
        "MATCH (parent:Directory {path: rel.parent}) MATCH (child:Directory {path: rel.child}) MERGE (parent)-[:CONTAINS]->(child)"
        in joined
    )


def test_create_imports_batches_and_links_dependencies():
    from src.analysis.code_analysis import create_imports

    files_data = [
        {
            "path": "src/A.java",
            "imports": [
                {
                    "import_path": "com.fasterxml.jackson.core.JsonFactory",
                    "import_type": "external",
                    "file": "src/A.java",
                    "is_static": False,
                    "is_wildcard": False,
                },
                {
                    "import_path": "java.util.List",
                    "import_type": "standard",
                    "file": "src/A.java",
                    "is_static": False,
                    "is_wildcard": False,
                },
            ],
        }
    ]
    dep_versions = {
        "com.fasterxml.jackson.core": "2.15.0",
        "com.fasterxml.jackson.core:jackson-core:2.15.0": "2.15.0",
    }
    s = _FakeSession()
    create_imports(s, files_data, dep_versions)
    joined = "\n".join(q for q, _ in s.calls)
    # Import nodes and IMPORTS relationships
    assert "MERGE (i:Import {import_path: imp.import_path})" in joined
    assert "MERGE (f)-[:IMPORTS]->(i)" in joined
    # ExternalDependency creation and linking should go via versioned node
    assert (
        "MERGE (e:ExternalDependency {group_id: dep.group_id, artifact_id: dep.artifact_id, version: dep.version})"
        in joined
    )
    assert "MERGE (i)-[:DEPENDS_ON]->(ed)" in joined
