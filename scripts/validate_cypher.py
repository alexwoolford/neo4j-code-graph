#!/usr/bin/env python3
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from neo4j import GraphDatabase


@dataclass
class DbConfig:
    uri: str
    username: str
    password: str
    database: str


def get_db_config() -> DbConfig:
    return DbConfig(
        uri=os.getenv("NEO4J_URI", "neo4j://localhost"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "neo4j"),
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )


def explain(
    session, query: str, params: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str]]:
    try:
        session.run("EXPLAIN " + query, **(params or {})).consume()
        return True, None
    except Exception as e:
        return False, str(e)


def run_validation(session) -> List[Tuple[str, bool, Optional[str]]]:
    results: List[Tuple[str, bool, Optional[str]]] = []

    # Basic sanity queries
    sanity_queries: List[Tuple[str, str, Dict[str, Any]]] = [
        ("simple_param", "RETURN $x AS v", {"x": 1}),
        ("unwind_list", "UNWIND $list AS x RETURN x", {"list": [1, 2, 3]}),
    ]

    for name, q, p in sanity_queries:
        ok, err = explain(session, q, p)
        results.append((name, ok, err))

    # Representative write-pattern queries from codebase (EXPLAIN only)
    tests: List[Tuple[str, str, Dict[str, Any]]] = [
        (
            "create_directories",
            "UNWIND $directories AS dir_path MERGE (:Directory {path: dir_path})",
            {"directories": ["/tmp/dir1", "/tmp/dir2"]},
        ),
        (
            "directory_rels",
            "UNWIND $rels AS rel MATCH (parent:Directory {path: rel.parent}) MATCH (child:Directory {path: rel.child}) MERGE (parent)-[:CONTAINS]->(child)",
            {"rels": [{"parent": "/tmp", "child": "/tmp/dir1"}]},
        ),
        (
            "file_nodes",
            "UNWIND $files AS file MERGE (f:File {path: file.path}) SET f.language = file.language",
            {"files": [{"path": "src/Main.java", "language": "java"}]},
        ),
        (
            "file_dir_rels",
            "UNWIND $rels AS rel MATCH (d:Directory {path: rel.directory}) MATCH (f:File {path: rel.file}) MERGE (d)-[:CONTAINS]->(f)",
            {"rels": [{"file": "src/Main.java", "directory": "src"}]},
        ),
        (
            "class_nodes",
            "UNWIND $classes AS class MERGE (c:Class {name: class.name, file: class.file}) SET c.line = class.line",
            {"classes": [{"name": "Main", "file": "src/Main.java", "line": 1}]},
        ),
        (
            "interface_nodes",
            "UNWIND $interfaces AS interface MERGE (i:Interface {name: interface.name, file: interface.file}) SET i.method_count = interface.method_count",
            {"interfaces": [{"name": "Runnable", "file": "src/Main.java", "method_count": 1}]},
        ),
        (
            "class_extends",
            "UNWIND $inheritance AS rel MATCH (child:Class {name: rel.child, file: rel.child_file}) MERGE (parent:Class {name: rel.parent}) MERGE (child)-[:EXTENDS]->(parent)",
            {"inheritance": [{"child": "Child", "child_file": "src/C.java", "parent": "Base"}]},
        ),
        (
            "class_implements",
            "UNWIND $implementations AS rel MATCH (c:Class {name: rel.class, file: rel.class_file}) MERGE (i:Interface {name: rel.interface}) MERGE (c)-[:IMPLEMENTS]->(i)",
            {
                "implementations": [
                    {"class": "Main", "class_file": "src/Main.java", "interface": "Runnable"}
                ]
            },
        ),
        (
            "method_nodes",
            "UNWIND $methods AS method MERGE (m:Method {method_signature: method.method_signature}) SET m.name = method.name, m.file = method.file, m.line = method.line, m.class_name = method.class_name, m.is_static = method.is_static",
            {
                "methods": [
                    {
                        "method_signature": "com.example.Main#foo():void",
                        "name": "foo",
                        "class_name": "Main",
                        "file": "src/Main.java",
                        "line": 10,
                        "is_static": True,
                    }
                ]
            },
        ),
        (
            "method_file_rels",
            "UNWIND $rels AS rel MATCH (f:File {path: rel.file_path}) MATCH (m:Method {name: rel.method_name, file: rel.file_path, line: rel.method_line}) MERGE (f)-[:DECLARES]->(m)",
            {"rels": [{"file_path": "src/Main.java", "method_name": "foo", "method_line": 10}]},
        ),
        (
            "method_class_rels",
            "UNWIND $rels AS rel MATCH (m:Method {name: rel.method_name, file: rel.method_file, line: rel.method_line}) MATCH (c:Class {name: rel.class_name, file: rel.method_file}) MERGE (c)-[:CONTAINS_METHOD]->(m)",
            {
                "rels": [
                    {
                        "method_name": "foo",
                        "method_file": "src/Main.java",
                        "method_line": 10,
                        "class_name": "Main",
                    }
                ]
            },
        ),
        (
            "import_nodes",
            "UNWIND $imports AS imp MERGE (i:Import {import_path: imp.import_path}) SET i.import_type = imp.import_type",
            {"imports": [{"import_path": "org.example.Util", "import_type": "external"}]},
        ),
        (
            "imports_rels",
            "UNWIND $imports AS imp MATCH (f:File {path: imp.file}) MATCH (i:Import {import_path: imp.import_path}) MERGE (f)-[:IMPORTS]->(i)",
            {"imports": [{"file": "src/Main.java", "import_path": "org.example.Util"}]},
        ),
        (
            "external_dep_link",
            "MATCH (i:Import) WHERE i.import_type = 'external' WITH i, SPLIT(i.import_path, '.') AS parts WHERE SIZE(parts) >= 3 WITH i, parts[0] + '.' + parts[1] + '.' + parts[2] AS base_package MATCH (e:ExternalDependency {package: base_package}) MERGE (i)-[:DEPENDS_ON]->(e)",
            {},
        ),
        (
            "calls_same_class",
            "UNWIND $calls AS call MATCH (caller:Method {name: call.caller_name, file: call.caller_file, line: call.caller_line}) MATCH (callee:Method {name: call.callee_name, class_name: call.callee_class}) WHERE caller.file = callee.file MERGE (caller)-[:CALLS {type: call.call_type}]->(callee)",
            {
                "calls": [
                    {
                        "caller_name": "foo",
                        "caller_file": "src/Main.java",
                        "caller_line": 10,
                        "callee_name": "bar",
                        "callee_class": "Main",
                        "call_type": "same_class",
                    }
                ]
            },
        ),
        (
            "calls_static",
            "UNWIND $calls AS call MATCH (caller:Method {name: call.caller_name, file: call.caller_file, line: call.caller_line}) MATCH (callee:Method {name: call.callee_name, class_name: call.callee_class}) WHERE callee.is_static = true MERGE (caller)-[:CALLS {type: call.call_type, qualifier: call.qualifier}]->(callee)",
            {
                "calls": [
                    {
                        "caller_name": "foo",
                        "caller_file": "src/Main.java",
                        "caller_line": 10,
                        "callee_name": "bar",
                        "callee_class": "Main",
                        "call_type": "static",
                        "qualifier": "Main",
                    }
                ]
            },
        ),
        (
            "calls_exists",
            "UNWIND $calls AS call MATCH (caller:Method {name: call.caller_name, file: call.caller_file, line: call.caller_line}) WHERE EXISTS { MATCH (callee:Method {name: call.callee_name}) WHERE callee.name = call.callee_name } WITH caller, call MATCH (callee:Method {name: call.callee_name}) WITH caller, callee, call LIMIT 1000 MERGE (caller)-[:CALLS {type: call.call_type, qualifier: call.qualifier}]->(callee) RETURN count(*) as created",
            {
                "calls": [
                    {
                        "caller_name": "foo",
                        "caller_file": "src/Main.java",
                        "caller_line": 10,
                        "callee_name": "bar",
                        "call_type": "instance",
                        "qualifier": "obj",
                    }
                ]
            },
        ),
        (
            "cve_impact_sample",
            "MATCH (cve:CVE)-[:AFFECTS]->(ed:ExternalDependency) MATCH (ed)<-[:DEPENDS_ON]-(i:Import)<-[:IMPORTS]-(f:File) WHERE f.path CONTAINS 'api' OPTIONAL MATCH (f)-[:DECLARES]->(m:Method {is_public: true}) RETURN cve LIMIT 1",
            {},
        ),
    ]

    for name, q, p in tests:
        ok, err = explain(session, q, p)
        results.append((name, ok, err))

    return results


def main() -> int:
    cfg = get_db_config()
    driver = GraphDatabase.driver(cfg.uri, auth=(cfg.username, cfg.password))
    failed: List[Tuple[str, str]] = []

    with driver.session(database=cfg.database) as session:
        # Connectivity sanity check
        session.run("RETURN 1").consume()

        results = run_validation(session)

    for name, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if err:
            print(f"  -> {err}")
        if not ok:
            failed.append((name, err or "Unknown error"))

    print(
        f"\nSummary: {len([r for r in results if r[1]])} passed, {len([r for r in results if not r[1]])} failed"
    )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
