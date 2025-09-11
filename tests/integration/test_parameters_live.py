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
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


def test_parameters_created_and_linked_with_package_resolution():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_methods,
    )
    from src.data.schema_management import setup_complete_schema

    # Two types in package p
    files_data = [
        {
            "path": "src/p/A.java",
            "classes": [
                {"name": "A", "file": "src/p/A.java", "package": "p", "line": 1, "implements": []}
            ],
            "interfaces": [
                {"name": "I", "file": "src/p/A.java", "package": "p", "line": 2, "extends": []}
            ],
            "methods": [],
        },
        {
            "path": "src/p/P.java",
            "classes": [
                {"name": "P", "file": "src/p/P.java", "package": "p", "line": 1, "implements": []}
            ],
            "methods": [
                {
                    "name": "use",
                    "file": "src/p/P.java",
                    "line": 10,
                    "method_signature": "p.P#use(p.A,p.I):void",
                    "class_name": "P",
                    "containing_type": "class",
                    "return_type": "void",
                    "is_public": True,
                    # parameters include type + type_package (resolver in extractor does this; we provide explicitly)
                    "parameters": [
                        {"name": "a", "type": "A", "type_package": "p"},
                        {"name": "i", "type": "I", "type_package": "p"},
                    ],
                }
            ],
        },
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

            # Two parameters created with correct indices
            rec = s.run(
                """
                MATCH (:Method {method_signature:'p.P#use(p.A,p.I):void'})-[:HAS_PARAMETER]->(p:Parameter)
                RETURN count(p) AS c, min(p.index) AS minIdx, max(p.index) AS maxIdx
                """
            ).single()
            assert (
                rec and int(rec["c"]) == 2 and int(rec["minIdx"]) == 0 and int(rec["maxIdx"]) == 1
            )

            # OF_TYPE links to Class and Interface in package p
            rec = s.run(
                """
                MATCH (:Method {method_signature:'p.P#use(p.A,p.I):void'})-[:HAS_PARAMETER]->(:Parameter)-[:OF_TYPE]->(t)
                RETURN collect(labels(t)) AS labs, count(*) AS c
                """
            ).single()
            assert rec and int(rec["c"]) == 2


def test_parameter_type_ambiguous_does_not_link():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_methods,
    )
    from src.data.schema_management import setup_complete_schema

    # Create two Z types in different packages and a method that references Z without package
    files_data = [
        {
            "path": "src/p1/Z.java",
            "classes": [
                {"name": "Z", "file": "src/p1/Z.java", "package": "p1", "line": 1, "implements": []}
            ],
            "methods": [],
        },
        {
            "path": "src/p2/Z.java",
            "classes": [
                {"name": "Z", "file": "src/p2/Z.java", "package": "p2", "line": 1, "implements": []}
            ],
            "methods": [],
        },
        {
            "path": "src/Q.java",
            "classes": [{"name": "Q", "file": "src/Q.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "m",
                    "file": "src/Q.java",
                    "line": 5,
                    "method_signature": "Q#m(Z):void",
                    "class_name": "Q",
                    "containing_type": "class",
                    "return_type": "void",
                    # ambiguous: type_package omitted
                    "parameters": [{"name": "z", "type": "Z"}],
                }
            ],
        },
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

            # Parameter exists
            rec = s.run(
                "MATCH (:Method {method_signature:'Q#m(Z):void'})-[:HAS_PARAMETER]->(p:Parameter) RETURN count(p) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            # But no OF_TYPE link due to ambiguity
            rec = s.run(
                "MATCH (:Method {method_signature:'Q#m(Z):void'})-[:HAS_PARAMETER]->(:Parameter)-[:OF_TYPE]->(t) RETURN count(t) AS c"
            ).single()
            assert rec and int(rec["c"]) == 0


def test_value_query_public_api_exposes_internal_types():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_methods,
    )
    from src.data.schema_management import setup_complete_schema

    # Define api and internal packages; method in api uses internal class as param
    files_data = [
        {
            "path": "api/Controller.java",
            "classes": [
                {
                    "name": "Controller",
                    "file": "api/Controller.java",
                    "package": "com.app.api",
                    "line": 1,
                    "implements": [],
                }
            ],
            "methods": [
                {
                    "name": "create",
                    "file": "api/Controller.java",
                    "line": 10,
                    "method_signature": "com.app.api.Controller#create(com.app.internal.Model):void",
                    "class_name": "Controller",
                    "containing_type": "class",
                    "return_type": "void",
                    "is_public": True,
                    "parameters": [
                        {"name": "m", "type": "Model", "type_package": "com.app.internal"}
                    ],
                }
            ],
        },
        {
            "path": "internal/Model.java",
            "classes": [
                {
                    "name": "Model",
                    "file": "internal/Model.java",
                    "package": "com.app.internal",
                    "line": 1,
                    "implements": [],
                }
            ],
            "methods": [],
        },
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

            # Query: Public API methods whose parameter type is in internal package
            q = (
                "MATCH (api:Class) WHERE api.package STARTS WITH 'com.app.api' "
                "MATCH (api)-[:CONTAINS_METHOD]->(m:Method {is_public:true}) "
                "MATCH (m)-[:HAS_PARAMETER]->(:Parameter)-[:OF_TYPE]->(t) "
                "WHERE t.package STARTS WITH 'com.app.internal' "
                "RETURN m.method_signature AS sig, api.name AS clazz, t.name AS leakType"
            )
            rows = list(s.run(q))
            assert rows and rows[0]["sig"].startswith("com.app.api.Controller#create(")

            # Bonus: constructor creates link
            # Add a constructor call to the controller method body via calls list
            files_data2 = [
                {
                    "path": "api/Controller.java",
                    "classes": [
                        {
                            "name": "Controller",
                            "file": "api/Controller.java",
                            "package": "com.app.api",
                            "line": 1,
                        }
                    ],
                    "methods": [
                        {
                            "name": "mk",
                            "file": "api/Controller.java",
                            "line": 20,
                            "method_signature": "com.app.api.Controller#mk():void",
                            "class_name": "Controller",
                            "containing_type": "class",
                            "return_type": "void",
                            "is_public": True,
                            "parameters": [],
                            "calls": [
                                {
                                    "method_name": "Model",
                                    "target_class": "Model",
                                    "target_package": "com.app.internal",
                                    "call_type": "constructor",
                                }
                            ],
                        }
                    ],
                }
            ]
            create_methods(s, files_data2, method_embeddings=[])
            rec = s.run(
                "MATCH (:Method {method_signature:'com.app.api.Controller#mk():void'})-[:CREATES]->(:Class {name:'Model', package:'com.app.internal'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1


def test_constructor_ambiguous_does_not_create():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_methods,
    )
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "p1/Z.java",
            "classes": [{"name": "Z", "file": "p1/Z.java", "package": "p1", "line": 1}],
            "methods": [],
        },
        {
            "path": "p2/Z.java",
            "classes": [{"name": "Z", "file": "p2/Z.java", "package": "p2", "line": 1}],
            "methods": [],
        },
        {
            "path": "Q.java",
            "classes": [{"name": "Q", "file": "Q.java", "line": 1}],
            "methods": [
                {
                    "name": "m",
                    "file": "Q.java",
                    "line": 5,
                    "method_signature": "Q#m():void",
                    "class_name": "Q",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "calls": [
                        {"method_name": "Z", "target_class": "Z", "call_type": "constructor"}
                    ],
                }
            ],
        },
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

            rec = s.run(
                "MATCH (:Method {method_signature:'Q#m():void'})-[:CREATES]->(:Class {name:'Z'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 0
