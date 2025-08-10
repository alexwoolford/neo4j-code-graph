import os
import sys
from pathlib import Path

import pytest


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


@pytest.mark.integration
def test_write_imports_and_calls_end_to_end():
    add_src_to_path()
    from analysis.code_analysis import (
        build_method_signature,
        create_directories,
        create_files,
        create_imports,
        create_method_calls,
        create_methods,
    )
    from utils.common import create_neo4j_driver

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    if not uri or not username or not password:
        pytest.skip("NEO4J connection not configured for integration test")

    files_data = [
        {
            "path": "com/demo/Demo.java",
            "code": "",
            "imports": [
                {
                    "import_path": "java.util.List",
                    "is_static": False,
                    "is_wildcard": False,
                    "import_type": "standard",
                    "file": "com/demo/Demo.java",
                }
            ],
            "classes": [
                {
                    "name": "Demo",
                    "type": "class",
                    "file": "com/demo/Demo.java",
                    "package": "com.demo",
                    "line": 1,
                    "modifiers": [],
                }
            ],
            "interfaces": [],
            "methods": [
                {
                    "name": "run",
                    "class_name": "Demo",
                    "containing_type": "class",
                    "line": 5,
                    "code": "",
                    "file": "com/demo/Demo.java",
                    "estimated_lines": 3,
                    "parameters": [],
                    "modifiers": [],
                    "is_static": False,
                    "is_abstract": False,
                    "is_final": False,
                    "is_private": False,
                    "is_public": True,
                    "return_type": "void",
                    "calls": [
                        {
                            "method_name": "help",
                            "target_class": "Helper",
                            "qualifier": "Helper",
                            "call_type": "static",
                        }
                    ],
                },
                {
                    "name": "help",
                    "class_name": "Helper",
                    "containing_type": "class",
                    "line": 10,
                    "code": "",
                    "file": "com/demo/Demo.java",
                    "estimated_lines": 1,
                    "parameters": [],
                    "modifiers": ["static"],
                    "is_static": True,
                    "is_abstract": False,
                    "is_final": False,
                    "is_private": False,
                    "is_public": True,
                    "return_type": "void",
                    "calls": [],
                },
            ],
            "language": "java",
            "ecosystem": "maven",
            "total_lines": 20,
            "code_lines": 10,
            "method_count": 2,
            "class_count": 1,
            "interface_count": 0,
        }
    ]

    # Populate required method_signature fields for writer
    for m in files_data[0]["methods"]:
        m["method_signature"] = build_method_signature(
            "com.demo",
            m.get("class_name"),
            m["name"],
            m.get("parameters", []),
            m.get("return_type"),
        )

    try:
        driver_ctx = create_neo4j_driver(uri, username, password)
    except Exception as e:
        pytest.skip(f"Neo4j not reachable for end-to-end write: {e}")

    with driver_ctx as driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

            create_directories(session, files_data)
            # Provide minimal dummy embeddings required by writers
            file_embeddings = {0: [0.0, 0.0, 0.0]}
            method_embeddings = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]

            create_files(session, files_data, file_embeddings=file_embeddings)
            create_methods(session, files_data, method_embeddings=method_embeddings)
            create_imports(session, files_data)
            create_method_calls(session, files_data)

            cnt = (
                session.run("MATCH (i:Import {import_path:'java.util.List'}) RETURN count(i) AS c")
                .single()
                .get("c")
            )
            assert cnt == 1
            m_cnt = session.run("MATCH (m:Method) RETURN count(m) AS c").single()["c"]
            assert m_cnt == 2
            calls = (
                session.run(
                    "MATCH (:Method{name:'run'})-[:CALLS]->(:Method{name:'help'}) RETURN count(*) AS c"
                )
                .single()
                .get("c")
            )
            assert calls == 1
