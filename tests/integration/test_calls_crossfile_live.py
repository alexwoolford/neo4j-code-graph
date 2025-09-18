#!/usr/bin/env python3

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_cross_file_static_call_resolution(tmp_path):
    # Arrange: two files in same package; Helper in separate file with static method
    pkg_dir = tmp_path / "com" / "demo"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "Helper.java").write_text(
        ("package com.demo;\n" "public class Helper {\n" "  public static void help() {}\n" "}\n"),
        encoding="utf-8",
    )
    (pkg_dir / "Demo.java").write_text(
        (
            "package com.demo;\n"
            "import com.demo.Helper;\n"
            "public class Demo {\n"
            "  public void run(){\n"
            "    Helper.help();\n"
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    # Minimal extraction using tree-sitter utility
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

    repo_root = tmp_path
    helper_fd = extract_file_data(pkg_dir / "Helper.java", repo_root)
    demo_fd = extract_file_data(pkg_dir / "Demo.java", repo_root)

    # Populate method signatures expected by writers
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

            # Act: write graph
            create_directories(session, files_data)
            create_files(session, files_data, file_embeddings=[[0.0]] * len(files_data))
            create_classes(session, files_data)
            # two methods total
            all_methods = [m for fd in files_data for m in fd.get("methods", [])]
            create_methods(session, files_data, method_embeddings=[[0.0]] * len(all_methods))
            create_imports(session, files_data)
            create_method_calls(session, files_data)

            # Assert: CALLS exists across files Demo.run -> Helper.help
            c = (
                session.run(
                    """
                    MATCH (:Method {name:'run'})-[:CALLS]->(:Method {name:'help'})
                    RETURN count(*) AS c
                    """
                )
                .single()
                .get("c")
            )
            assert c == 1
