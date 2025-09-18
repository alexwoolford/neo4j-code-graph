#!/usr/bin/env python3

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_cross_file_instance_call_unique_in_file(tmp_path):
    # Arrange: Demo.run calls helper.qux(), Helper has unique method qux()
    pkg = tmp_path / "com" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "Helper.java").write_text(
        ("package com.demo;\n" "public class Helper {\n" "  public void qux() {}\n" "}\n"),
        encoding="utf-8",
    )
    (pkg / "Demo.java").write_text(
        (
            "package com.demo;\n"
            "public class Demo {\n"
            "  public void run(){\n"
            "    Helper h = new Helper();\n"
            "    h.qux();\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    from src.analysis.java_treesitter import extract_file_data
    from src.analysis.parser import build_method_signature
    from src.data.graph_writer import (
        create_classes,
        create_directories,
        create_files,
        create_imports,
        create_method_calls,
        create_methods,
    )
    from src.utils.common import create_neo4j_driver
    from src.utils.neo4j_utils import get_neo4j_config

    helper_fd = extract_file_data(pkg / "Helper.java", tmp_path)
    demo_fd = extract_file_data(pkg / "Demo.java", tmp_path)

    for fd in (helper_fd, demo_fd):
        for m in fd["methods"]:
            m["method_signature"] = build_method_signature(
                fd.get("classes", [{}])[0].get("package"),
                m.get("class_name"),
                m["name"],
                m.get("parameters", []),
                m.get("return_type"),
            )

    files_data = [helper_fd, demo_fd]

    uri, username, password, database = get_neo4j_config()
    try:
        driver_ctx = create_neo4j_driver(uri, username, password)
    except Exception as e:
        pytest.skip(f"Neo4j not reachable: {e}")

    with driver_ctx as driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

            create_directories(session, files_data)
            create_files(session, files_data, file_embeddings=[[0.0]] * len(files_data))
            create_classes(session, files_data)
            all_methods = [m for fd in files_data for m in fd.get("methods", [])]
            create_methods(session, files_data, method_embeddings=[[0.0]] * len(all_methods))
            create_imports(session, files_data)
            create_method_calls(session, files_data)

            c = (
                session.run(
                    "MATCH (:Method {name:'run'})-[:CALLS]->(:Method {name:'qux'}) RETURN count(*) AS c"
                )
                .single()
                .get("c")
            )
            assert c == 1
