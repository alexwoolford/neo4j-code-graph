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


def test_live_directories_imports_and_depends_on():
    from src.analysis.code_analysis import create_directories, create_imports
    from src.data.schema_management import setup_complete_schema

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

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)

            create_directories(s, files_data)
            create_imports(s, files_data, dep_versions)

            # Assert directory root and child exist and DEPENDS_ON link created
            rec = s.run("MATCH (d:Directory) RETURN count(d) AS c").single()
            assert rec and int(rec["c"]) >= 1
            rec = s.run(
                "MATCH (:Import)-[:DEPENDS_ON]->(:ExternalDependency) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1


def test_live_methods_and_relationships_created():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_methods,
    )
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "src/A.java",
            "classes": [
                {"name": "A", "file": "src/A.java", "line": 1, "implements": []},
            ],
            "interfaces": [
                {"name": "I", "file": "src/A.java", "line": 2, "extends": []},
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
                },
                {
                    "name": "m2",
                    "file": "src/A.java",
                    "line": 20,
                    "method_signature": "p.I#m2():void",
                    "class_name": "I",
                    "containing_type": "interface",
                    "return_type": "void",
                    "parameters": [],
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

            # Asserts
            # Methods created
            rec = s.run("MATCH (m:Method) RETURN count(m) AS c").single()
            assert rec and int(rec["c"]) == 2
            # File DECLARES method
            rec = s.run("MATCH (:File)-[:DECLARES]->(:Method) RETURN count(*) AS c").single()
            assert rec and int(rec["c"]) >= 2
            # Class contains method m1
            rec = s.run(
                "MATCH (c:Class {name:'A'})-[:CONTAINS_METHOD]->(m:Method {name:'m1'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            # Interface contains method m2
            rec = s.run(
                "MATCH (i:Interface {name:'I'})-[:CONTAINS_METHOD]->(m:Method {name:'m2'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1


def test_live_class_inheritance_and_implements():
    from src.analysis.code_analysis import create_classes, create_directories, create_files
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "src/inherit/A.java",
            "classes": [
                {
                    "name": "A",
                    "file": "src/inherit/A.java",
                    "line": 1,
                    "extends": "B",
                    "implements": ["I"],
                }
            ],
            "interfaces": [
                {"name": "I", "file": "src/inherit/A.java", "line": 2, "extends": ["J"]}
            ],
            "methods": [],
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

            # A EXTENDS B (class inheritance)
            rec = s.run(
                "MATCH (:Class {name:'A'})-[:EXTENDS]->(:Class {name:'B'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            # A IMPLEMENTS I (class implements interface)
            rec = s.run(
                "MATCH (:Class {name:'A'})-[:IMPLEMENTS]->(:Interface {name:'I'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            # I EXTENDS J (interface inheritance)
            rec = s.run(
                "MATCH (:Interface {name:'I'})-[:EXTENDS]->(:Interface {name:'J'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1


def test_live_method_calls_smoke():
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
            "path": "src/B.java",
            "classes": [
                {"name": "C", "file": "src/B.java", "line": 1, "implements": []},
            ],
            "methods": [
                {
                    "name": "caller",
                    "file": "src/B.java",
                    "line": 10,
                    "method_signature": "p.C#caller():void",
                    "class_name": "C",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "b();",
                    "calls": [{"method_name": "b", "target_class": "C", "call_type": "same_class"}],
                },
                {
                    "name": "b",
                    "file": "src/B.java",
                    "line": 20,
                    "method_signature": "p.C#b():void",
                    "class_name": "C",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                    "calls": [],
                },
                {
                    "name": "staticMeth",
                    "file": "src/B.java",
                    "line": 30,
                    "method_signature": "p.C#staticMeth():void",
                    "class_name": "C",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "is_static": True,
                    "code": "",
                    "calls": [],
                },
                {
                    "name": "caller2",
                    "file": "src/B.java",
                    "line": 40,
                    "method_signature": "p.C#caller2():void",
                    "class_name": "C",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "C.staticMeth();",
                    "calls": [
                        {
                            "method_name": "staticMeth",
                            "target_class": "C",
                            "call_type": "static",
                            "qualifier": "C",
                        }
                    ],
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
            create_method_calls(s, files_data)

            # Same-class call exists
            rec = s.run(
                "MATCH (:Class {name:'C'})-[:CONTAINS_METHOD]->(:Method {name:'caller'})-[:CALLS]->(:Method {name:'b'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            # Static call exists and callee marked static
            rec = s.run(
                "MATCH (:Method {name:'caller2'})-[:CALLS {type:'static'}]->(m:Method {name:'staticMeth'}) RETURN count(m) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            rec = s.run("MATCH (m:Method {name:'staticMeth'}) RETURN m.is_static AS s").single()
            assert rec and bool(rec["s"]) is True


def test_live_cross_file_inheritance_and_implements():
    from src.analysis.code_analysis import create_classes, create_directories, create_files
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "pkg1/A.java",
            "classes": [{"name": "A", "file": "pkg1/A.java", "line": 1, "implements": ["I"]}],
            "interfaces": [],
            "methods": [],
        },
        {
            "path": "pkg2/B.java",
            "classes": [{"name": "B", "file": "pkg2/B.java", "line": 1, "extends": "A"}],
            "interfaces": [{"name": "I", "file": "pkg2/B.java", "line": 2, "extends": []}],
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

            rec = s.run(
                "MATCH (:Class {name:'B'})-[:EXTENDS]->(:Class {name:'A'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            rec = s.run(
                "MATCH (:Class {name:'A'})-[:IMPLEMENTS]->(:Interface {name:'I'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1


def test_live_method_calls_instance_other_branch():
    from src.analysis.code_analysis import (
        create_classes,
        create_directories,
        create_files,
        create_method_calls,
        create_methods,
    )
    from src.data.schema_management import setup_complete_schema

    # Two classes; C1.caller invokes C2.target() as an instance call
    files_data = [
        {
            "path": "src/C1.java",
            "classes": [{"name": "C1", "file": "src/C1.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "caller",
                    "file": "src/C1.java",
                    "line": 10,
                    "method_signature": "p.C1#caller():void",
                    "class_name": "C1",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "c2.target();",
                    "calls": [
                        {
                            "method_name": "target",
                            "target_class": "C2",
                            "call_type": "instance",
                            "qualifier": "c2",
                        }
                    ],
                }
            ],
        },
        {
            "path": "src/C2.java",
            "classes": [{"name": "C2", "file": "src/C2.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "target",
                    "file": "src/C2.java",
                    "line": 20,
                    "method_signature": "p.C2#target():void",
                    "class_name": "C2",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
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
            create_method_calls(s, files_data)

            rec = s.run(
                "MATCH (:Method {name:'caller'})-[:CALLS {type:'instance', qualifier:'c2'}]->(:Method {name:'target'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1


def test_live_bulk_create_smoke():
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "s1/A.java",
            "classes": [{"name": "A", "file": "s1/A.java", "line": 1, "implements": []}],
            "interfaces": [],
            "imports": [
                {
                    "import_path": "org.example.lib.Core",
                    "import_type": "external",
                    "file": "s1/A.java",
                    "is_static": False,
                    "is_wildcard": False,
                }
            ],
            "methods": [
                {
                    "name": "m",
                    "file": "s1/A.java",
                    "line": 5,
                    "method_signature": "p.A#m():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                }
            ],
        }
    ]

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)

            bulk_create_nodes_and_relationships(
                s,
                files_data,
                file_embeddings=[],
                method_embeddings=[],
                dependency_versions={"org.example.lib:core:1.0.0": "1.0.0"},
            )

            # Sanity checks: File, Class, Method, Import, Dependency, and some rels
            rec = s.run("MATCH (f:File) RETURN count(f) AS c").single()
            assert rec and int(rec["c"]) == 1
            rec = s.run("MATCH (c:Class) RETURN count(c) AS c").single()
            assert rec and int(rec["c"]) == 1
            rec = s.run("MATCH (m:Method) RETURN count(m) AS c").single()
            assert rec and int(rec["c"]) == 1
            rec = s.run("MATCH (i:Import) RETURN count(i) AS c").single()
            assert rec and int(rec["c"]) == 1
            rec = s.run("MATCH (e:ExternalDependency) RETURN count(e) AS c").single()
            assert rec and int(rec["c"]) >= 1


def test_live_imports_set_gav_properties():
    from src.analysis.code_analysis import create_directories, create_files, create_imports
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "src/Gav.java",
            "imports": [
                {
                    "import_path": "com.fasterxml.jackson.core.JsonFactory",
                    "import_type": "external",
                    "file": "src/Gav.java",
                    "is_static": False,
                    "is_wildcard": False,
                }
            ],
            "methods": [],
        }
    ]
    dep_versions = {
        "com.fasterxml.jackson.core:jackson-core:2.15.0": "2.15.0",
        "com.fasterxml.jackson.core": "2.15.0",
    }

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)
            create_directories(s, files_data)
            create_files(s, files_data, file_embeddings=[])
            create_imports(s, files_data, dep_versions)

            rec = s.run(
                """
                MATCH (i:Import)-[:DEPENDS_ON]->(e:ExternalDependency {package:'com.fasterxml.jackson'})
                RETURN e.version AS v, e.group_id AS g, e.artifact_id AS a
                """
            ).single()
            assert rec is not None
            assert rec["v"] == "2.15.0"
            # group_id/artifact_id may be unset for 3-part base packages; allow None
            assert rec["g"] is None or isinstance(rec["g"], str)
            assert rec["a"] is None or isinstance(rec["a"], str)


def test_live_imports_idempotent():
    from src.analysis.code_analysis import create_directories, create_files, create_imports
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "src/Idem.java",
            "imports": [
                {
                    "import_path": "org.acme.pkg.Widget",
                    "import_type": "external",
                    "file": "src/Idem.java",
                    "is_static": False,
                    "is_wildcard": False,
                }
            ],
            "methods": [],
        }
    ]
    dep_versions = {"org.acme.pkg": "1.2.3"}

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)
            for _ in range(2):
                create_directories(s, files_data)
                create_files(s, files_data, file_embeddings=[])
                create_imports(s, files_data, dep_versions)

            rec_i = s.run("MATCH (i:Import) RETURN count(i) AS c").single()
            rec_e = s.run("MATCH (e:ExternalDependency) RETURN count(e) AS c").single()
            rec_d = s.run(
                "MATCH (:Import)-[r:DEPENDS_ON]->(:ExternalDependency) RETURN count(r) AS c"
            ).single()
            assert int(rec_i["c"]) == 1
            assert int(rec_e["c"]) == 1
            assert int(rec_d["c"]) == 1


def test_live_bulk_idempotent():
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "idem/B.java",
            "classes": [{"name": "B", "file": "idem/B.java", "line": 1, "implements": []}],
            "interfaces": [],
            "imports": [
                {
                    "import_path": "org.sample.lib.Core",
                    "import_type": "external",
                    "file": "idem/B.java",
                    "is_static": False,
                    "is_wildcard": False,
                }
            ],
            "methods": [
                {
                    "name": "m",
                    "file": "idem/B.java",
                    "line": 10,
                    "method_signature": "q.B#m():void",
                    "class_name": "B",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                }
            ],
        }
    ]

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)

            for _ in range(2):
                bulk_create_nodes_and_relationships(
                    s,
                    files_data,
                    file_embeddings=[],
                    method_embeddings=[],
                    dependency_versions={"org.sample.lib:core:9.9.9": "9.9.9"},
                )

            # Counts should remain stable after repeated runs
            counts = {
                "File": s.run("MATCH (n:File) RETURN count(n) AS c").single()["c"],
                "Class": s.run("MATCH (n:Class) RETURN count(n) AS c").single()["c"],
                "Method": s.run("MATCH (n:Method) RETURN count(n) AS c").single()["c"],
                "Import": s.run("MATCH (n:Import) RETURN count(n) AS c").single()["c"],
                "ExternalDependency": s.run(
                    "MATCH (n:ExternalDependency) RETURN count(n) AS c"
                ).single()["c"],
            }
            assert counts == {
                "File": 1,
                "Class": 1,
                "Method": 1,
                "Import": 1,
                "ExternalDependency": 1,
            }


def test_live_multi_interfaces_and_multi_level_extends():
    from src.analysis.code_analysis import create_classes, create_directories, create_files
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "mlev/A.java",
            "classes": [{"name": "A", "file": "mlev/A.java", "line": 1, "implements": []}],
            "interfaces": [
                {"name": "J", "file": "mlev/A.java", "line": 2, "extends": []},
                {"name": "K", "file": "mlev/A.java", "line": 3, "extends": []},
            ],
            "methods": [],
        },
        {
            "path": "mlev/B.java",
            "classes": [{"name": "B", "file": "mlev/B.java", "line": 1, "extends": "A"}],
            "interfaces": [],
            "methods": [],
        },
        {
            "path": "mlev/C.java",
            "classes": [
                {"name": "C", "file": "mlev/C.java", "line": 1, "extends": "B"},
                {"name": "D", "file": "mlev/C.java", "line": 2, "implements": ["I", "K"]},
            ],
            "interfaces": [{"name": "I", "file": "mlev/C.java", "line": 3, "extends": ["J", "K"]}],
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

            # Multi-level class inheritance
            rec = s.run(
                "MATCH (:Class {name:'C'})-[:EXTENDS]->(:Class {name:'B'})-[:EXTENDS]->(:Class {name:'A'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            # Class implements multiple interfaces
            rec = s.run(
                "MATCH (:Class {name:'D'})-[:IMPLEMENTS]->(:Interface {name:'I'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            rec = s.run(
                "MATCH (:Class {name:'D'})-[:IMPLEMENTS]->(:Interface {name:'K'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            # Interface extends multiple interfaces
            rec = s.run(
                "MATCH (:Interface {name:'I'})-[:EXTENDS]->(:Interface {name:'J'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            rec = s.run(
                "MATCH (:Interface {name:'I'})-[:EXTENDS]->(:Interface {name:'K'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1


def test_live_bulk_with_calls_creates_calls():
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "calls2/A.java",
            "classes": [{"name": "A", "file": "calls2/A.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "a",
                    "file": "calls2/A.java",
                    "line": 10,
                    "method_signature": "r.A#a():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "b();",
                    "calls": [{"method_name": "b", "target_class": "A", "call_type": "same_class"}],
                },
                {
                    "name": "b",
                    "file": "calls2/A.java",
                    "line": 20,
                    "method_signature": "r.A#b():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                },
                {
                    "name": "s",
                    "file": "calls2/A.java",
                    "line": 30,
                    "method_signature": "r.A#s():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "is_static": True,
                    "code": "",
                },
                {
                    "name": "c",
                    "file": "calls2/A.java",
                    "line": 40,
                    "method_signature": "r.A#c():void",
                    "class_name": "A",
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
        }
    ]

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)

            bulk_create_nodes_and_relationships(
                s, files_data, file_embeddings=[], method_embeddings=[], dependency_versions=None
            )

            rec = s.run(
                "MATCH (:Method {name:'a'})-[:CALLS]->(:Method {name:'b'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
            rec = s.run(
                "MATCH (:Method {name:'c'})-[:CALLS {type:'static'}]->(:Method {name:'s'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1
