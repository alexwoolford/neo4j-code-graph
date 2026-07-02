"""Integration tests for the CALLS_EXTERNAL writer (PR8).

Builds files_data with methods + imports + calls (external static, instance on
a local receiver, wildcard-resolved static, and a JDK call), writes it through
create_imports + create_external_calls against the session-scoped testcontainer
database, and asserts confidence tiers, properties, and idempotency: re-running
the writer over identical files_data must leave the graph unchanged.
"""

import sys
from pathlib import Path

import pytest


def add_src_to_path() -> None:
    root = Path(__file__).parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


FILE_PATH = "com/demo/Demo.java"
RUN_SIG = "com.demo.Demo#run():void"
HELP_SIG = "com.demo.Demo#help():void"


def _files_data():
    return [
        {
            "path": FILE_PATH,
            "code": "",
            "imports": [
                {
                    "import_path": "com.fasterxml.jackson.databind.ObjectMapper",
                    "is_static": False,
                    "is_wildcard": False,
                    "import_type": "external",
                    "file": FILE_PATH,
                },
                {
                    "import_path": "com.google.common.collect",
                    "is_static": False,
                    "is_wildcard": True,
                    "import_type": "external",
                    "file": FILE_PATH,
                },
                {
                    "import_path": "java.util.List",
                    "is_static": False,
                    "is_wildcard": False,
                    "import_type": "standard",
                    "file": FILE_PATH,
                },
            ],
            "classes": [
                {
                    "name": "Demo",
                    "type": "class",
                    "file": FILE_PATH,
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
                    "file": FILE_PATH,
                    "estimated_lines": 6,
                    "parameters": [],
                    "modifiers": [],
                    "is_static": False,
                    "is_public": True,
                    "return_type": "void",
                    "method_signature": RUN_SIG,
                    "calls": [
                        # HIGH: static call, type pinned by explicit import
                        {
                            "method_name": "findModules",
                            "target_class": "ObjectMapper",
                            "target_package": "com.fasterxml.jackson.databind",
                            "call_type": "static",
                            "qualifier": "ObjectMapper",
                            "argc": 0,
                            "resolution": "explicit_import",
                            "receiver_source": "static_qualifier",
                        },
                        # MEDIUM: instance call on a local var of imported type,
                        # invoked twice -> call_count aggregation
                        {
                            "method_name": "readValue",
                            "target_class": "ObjectMapper",
                            "target_package": "com.fasterxml.jackson.databind",
                            "call_type": "instance",
                            "qualifier": "m",
                            "argc": 2,
                            "resolution": "explicit_import",
                            "receiver_source": "local",
                        },
                        {
                            "method_name": "readValue",
                            "target_class": "ObjectMapper",
                            "target_package": "com.fasterxml.jackson.databind",
                            "call_type": "instance",
                            "qualifier": "m",
                            "argc": 2,
                            "resolution": "explicit_import",
                            "receiver_source": "local",
                        },
                        # LOW: static call resolved via the single external wildcard
                        {
                            "method_name": "newArrayList",
                            "target_class": "Lists",
                            "target_package": "com.google.common.collect",
                            "call_type": "static",
                            "qualifier": "Lists",
                            "argc": 0,
                            "resolution": "wildcard_import",
                            "receiver_source": "static_qualifier",
                        },
                        # JDK call: must never become a frontier edge
                        {
                            "method_name": "add",
                            "target_class": "List",
                            "target_package": "java.util",
                            "call_type": "instance",
                            "qualifier": "xs",
                            "argc": 1,
                            "resolution": "explicit_import",
                            "receiver_source": "local",
                        },
                        # Internal call: not frontier material
                        {
                            "method_name": "help",
                            "target_class": None,
                            "target_package": None,
                            "call_type": "same_class",
                            "qualifier": "",
                            "argc": 0,
                            "resolution": None,
                            "receiver_source": None,
                        },
                    ],
                },
                {
                    "name": "help",
                    "class_name": "Demo",
                    "containing_type": "class",
                    "line": 15,
                    "code": "",
                    "file": FILE_PATH,
                    "estimated_lines": 1,
                    "parameters": [],
                    "modifiers": [],
                    "is_static": False,
                    "is_public": True,
                    "return_type": "void",
                    "method_signature": HELP_SIG,
                    "calls": [],
                },
            ],
            "language": "java",
            "ecosystem": "maven",
            "total_lines": 30,
            "code_lines": 20,
            "method_count": 2,
            "class_count": 1,
            "interface_count": 0,
        }
    ]


def _edge_rows(session):
    return {
        r["method_name"]: dict(r)
        for r in session.run(
            """
            MATCH (m:Method)-[r:CALLS_EXTERNAL]->(i:Import)
            RETURN m.method_signature AS sig, i.import_path AS import_path,
                   r.method_name AS method_name, r.target_class AS target_class,
                   r.call_type AS call_type, r.confidence AS confidence,
                   r.confidence_rank AS confidence_rank, r.resolution AS resolution,
                   r.receiver_source AS receiver_source, r.call_count AS call_count
            """
        )
    }


@pytest.mark.integration
def test_create_external_calls_tiers_and_idempotency(neo4j_driver):
    add_src_to_path()
    from src.data.graph_writer import (
        create_directories,
        create_external_calls,
        create_files,
        create_imports,
        create_methods,
    )

    files_data = _files_data()

    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()

        create_directories(session, files_data)
        create_files(session, files_data)
        create_methods(session, files_data)
        create_imports(session, files_data)
        create_external_calls(session, files_data)

        edges = _edge_rows(session)
        assert set(edges) == {"findModules", "readValue", "newArrayList"}

        high = edges["findModules"]
        assert high["sig"] == RUN_SIG
        assert high["import_path"] == "com.fasterxml.jackson.databind.ObjectMapper"
        assert high["confidence"] == "HIGH"
        assert high["confidence_rank"] == 3
        assert high["call_type"] == "static"
        assert high["target_class"] == "ObjectMapper"
        assert high["resolution"] == "explicit_import"
        assert high["receiver_source"] == "static_qualifier"
        assert high["call_count"] == 1

        medium = edges["readValue"]
        assert medium["import_path"] == "com.fasterxml.jackson.databind.ObjectMapper"
        assert medium["confidence"] == "MEDIUM"
        assert medium["confidence_rank"] == 2
        assert medium["receiver_source"] == "local"
        # Two identical call sites aggregate BEFORE writing
        assert medium["call_count"] == 2

        low = edges["newArrayList"]
        assert low["import_path"] == "com.google.common.collect"
        assert low["confidence"] == "LOW"
        assert low["confidence_rank"] == 1
        assert low["resolution"] == "wildcard_import"
        assert low["call_count"] == 1

        # Idempotency: re-running the writer over the SAME files_data is a
        # no-op — no duplicate edges, counts and tiers unchanged.
        create_external_calls(session, files_data)
        edges_after = _edge_rows(session)
        assert edges_after == edges
        total = session.run("MATCH ()-[r:CALLS_EXTERNAL]->() RETURN count(r) AS c").single()["c"]
        assert total == 3


@pytest.mark.integration
def test_bulk_create_wires_external_calls_after_imports(neo4j_driver):
    add_src_to_path()
    from src.data.graph_writer import bulk_create_nodes_and_relationships

    files_data = _files_data()

    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()

        bulk_create_nodes_and_relationships(session, files_data)

        rec = session.run(
            """
            MATCH (m:Method {method_signature: $sig})-[r:CALLS_EXTERNAL]->(i:Import)
            RETURN count(r) AS c, collect(DISTINCT i.import_path) AS paths
            """,
            sig=RUN_SIG,
        ).single()
        assert rec["c"] == 3
        assert set(rec["paths"]) == {
            "com.fasterxml.jackson.databind.ObjectMapper",
            "com.google.common.collect",
        }

        # End-to-end idempotency through the orchestrator as well.
        bulk_create_nodes_and_relationships(session, files_data)
        counts = session.run(
            """
            MATCH ()-[r:CALLS_EXTERNAL]->()
            RETURN count(r) AS edges, sum(r.call_count) AS total_calls
            """
        ).single()
        assert counts["edges"] == 3
        assert counts["total_calls"] == 4  # 1 + 2 + 1, not inflated by re-run
