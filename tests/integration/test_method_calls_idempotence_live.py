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
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


def test_method_calls_mixed_types_idempotent_live():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_method_calls,
        create_methods,
    )
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "mix/A.java",
            "classes": [{"name": "A", "file": "mix/A.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "a",
                    "file": "mix/A.java",
                    "line": 10,
                    "method_signature": "m.A#a():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "b(); A.s();",
                    "calls": [
                        {"method_name": "b", "target_class": "A", "call_type": "same_class"},
                        {
                            "method_name": "s",
                            "target_class": "A",
                            "call_type": "static",
                            "qualifier": "A",
                        },
                    ],
                },
                {
                    "name": "b",
                    "file": "mix/A.java",
                    "line": 20,
                    "method_signature": "m.A#b():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                },
                {
                    "name": "s",
                    "file": "mix/A.java",
                    "line": 30,
                    "method_signature": "m.A#s():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "is_static": True,
                    "code": "",
                },
            ],
        },
        {
            "path": "mix/B.java",
            "classes": [{"name": "B", "file": "mix/B.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "caller",
                    "file": "mix/B.java",
                    "line": 10,
                    "method_signature": "m.B#caller():void",
                    "class_name": "B",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "A.s();",
                    "calls": [
                        {
                            "method_name": "s",
                            "target_class": "A",
                            "call_type": "static",
                            "qualifier": "A",
                        }
                    ],
                },
            ],
        },
    ]

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)

            # Two runs to check idempotence
            for _ in range(2):
                create_directories(s, files_data)
                create_files(s, files_data, file_embeddings=[])
                create_classes(s, files_data)
                create_methods(s, files_data, method_embeddings=[])
                create_method_calls(s, files_data)

            r1 = s.run(
                "MATCH (:Method {name:'a'})-[:CALLS]->(:Method {name:'b'}) RETURN count(*) AS c"
            ).single()
            r2 = s.run(
                "MATCH (:Method {name:'a'})-[:CALLS {type:'static'}]->(:Method {name:'s'}) RETURN count(*) AS c"
            ).single()
            r3 = s.run(
                "MATCH (:Method {name:'caller'})-[:CALLS {type:'static'}]->(:Method {name:'s'}) RETURN count(*) AS c"
            ).single()
            assert int(r1["c"]) == 1 and int(r2["c"]) == 1 and int(r3["c"]) == 1
