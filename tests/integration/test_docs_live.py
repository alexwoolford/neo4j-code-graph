#!/usr/bin/env python3

import pytest

pytestmark = pytest.mark.live


def _get_driver_or_skip():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")
    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
        # Verify database exists; fallback to 'neo4j' if the configured one is missing
        try:
            with driver.session(database=db) as _s:
                _s.run("RETURN 1").consume()
            return driver, db
        except Exception:
            try:
                with driver.session(database="neo4j") as _s2:
                    _s2.run("RETURN 1").consume()
                return driver, "neo4j"
            except Exception:
                raise
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


def test_live_docs_created_and_linked():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_methods,
    )
    from src.data.graph_writer import create_docs
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "src/A.java",
            "classes": [
                {"name": "A", "file": "src/A.java", "line": 1, "implements": []},
            ],
            "methods": [
                {
                    "name": "m1",
                    "file": "src/A.java",
                    "line": 10,
                    "method_signature": "p.A#m1():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                    "cyclomatic_complexity": 1,
                }
            ],
            # Provide docs for class and method
            "docs": [
                {
                    "file": "src/A.java",
                    "language": "java",
                    "kind": "javadoc",
                    "start_line": 1,
                    "end_line": 3,
                    "text": "Class A doc",
                    "class_name": "A",
                    "scope": "class",
                },
                {
                    "file": "src/A.java",
                    "language": "java",
                    "kind": "line_comment",
                    "start_line": 9,
                    "end_line": 9,
                    "text": "Method m1 doc",
                    "method_signature": "p.A#m1():void",
                    "scope": "method",
                },
            ],
        }
    ]

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)

            create_directories(s, files_data)
            create_files(s, files_data, file_embeddings=[])
            create_classes(s, files_data)
            create_methods(s, files_data, method_embeddings=[])
            create_docs(s, files_data)

            # Doc nodes exist
            rec = s.run("MATCH (d:Doc) RETURN count(d) AS c").single()
            assert rec and int(rec["c"]) == 2

            # File HAS_DOC
            rec = s.run(
                "MATCH (:File {path:'src/A.java'})-[:HAS_DOC]->(:Doc {text:'Class A doc'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1

            # Method HAS_DOC via method_signature
            rec = s.run(
                "MATCH (:Method {method_signature:'p.A#m1():void'})-[:HAS_DOC]->(:Doc {text:'Method m1 doc'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1

            # Cyclomatic complexity present on method
            rec = s.run(
                "MATCH (m:Method {method_signature:'p.A#m1():void'}) RETURN m.cyclomatic_complexity AS cc"
            ).single()
            assert rec and int(rec["cc"]) >= 1

            # Kinds and scopes are stored
            rec = s.run(
                "MATCH (d:Doc {text:'Class A doc'}) RETURN d.kind AS k, d.scope AS s"
            ).single()
            assert rec and rec["k"] == "javadoc" and rec["s"] == "class"
            rec = s.run(
                "MATCH (d:Doc {text:'Method m1 doc'}) RETURN d.kind AS k, d.scope AS s"
            ).single()
            assert rec and rec["k"] == "line_comment" and rec["s"] == "method"
