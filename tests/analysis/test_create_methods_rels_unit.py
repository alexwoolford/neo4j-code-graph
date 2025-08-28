#!/usr/bin/env python3

from __future__ import annotations


class _FakeSession:
    def __init__(self):
        self.calls: list[str] = []

    def run(self, q: str, **params):
        self.calls.append(" ".join(q.split()))

        class _R:
            @staticmethod
            def consume():
                return None

        return _R()


def test_create_methods_relationship_cypher_shapes():
    from src.analysis.code_analysis import create_methods

    # Minimal files_data with both class and interface containing methods
    files_data = [
        {
            "path": "src/A.java",
            "methods": [
                {
                    "name": "m1",
                    "file": "src/A.java",
                    "line": 10,
                    "method_signature": "p.A#m1():void",
                    "class_name": "A",
                    "containing_type": "class",
                },
                {
                    "name": "m2",
                    "file": "src/A.java",
                    "line": 20,
                    "method_signature": "p.I#m2():void",
                    "class_name": "I",
                    "containing_type": "interface",
                },
            ],
        }
    ]
    s = _FakeSession()
    create_methods(s, files_data, method_embeddings=[])
    joined = "\n".join(s.calls)
    # Method-File rel
    assert "MATCH (f:File {path: rel.file_path})" in joined
    assert "MERGE (f)-[:DECLARES]->(m)" in joined
    # Method-Class rel
    assert "MATCH (c:Class {name: rel.class_name, file: rel.method_file})" in joined
    assert "MERGE (c)-[:CONTAINS_METHOD]->(m)" in joined
    # Method-Interface rel
    assert "MATCH (i:Interface {name: rel.interface_name, file: rel.method_file})" in joined
    assert "MERGE (i)-[:CONTAINS_METHOD]->(m)" in joined
