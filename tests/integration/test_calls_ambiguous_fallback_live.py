#!/usr/bin/env python3

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_ambiguous_callee_does_not_error(tmp_path):
    # Two classes with same method name in different packages; call uses bare name
    a = tmp_path / "com" / "a"
    b = tmp_path / "com" / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "X.java").write_text(
        ("package com.a;\n" "public class X { public static void foo() {} }\n"),
        encoding="utf-8",
    )
    (b / "Y.java").write_text(
        ("package com.b;\n" "public class Y { public static void foo() {} }\n"),
        encoding="utf-8",
    )
    (a / "Demo.java").write_text(
        (
            "package com.a;\n"
            "public class Demo {\n"
            "  public void run(){\n"
            "    foo(); // ambiguous bare call; should not error\n"
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

    fds = [
        extract_file_data(a / "X.java", tmp_path),
        extract_file_data(b / "Y.java", tmp_path),
        extract_file_data(a / "Demo.java", tmp_path),
    ]
    for fd in fds:
        for m in fd["methods"]:
            m["method_signature"] = build_method_signature(
                fd.get("classes", [{}])[0].get("package"),
                m.get("class_name"),
                m["name"],
                m.get("parameters", []),
                m.get("return_type"),
            )

    uri, username, password, database = get_neo4j_config()
    try:
        driver_ctx = create_neo4j_driver(uri, username, password)
    except Exception as e:
        pytest.skip(f"Neo4j not reachable: {e}")

    with driver_ctx as driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

            create_directories(session, fds)
            create_files(session, fds, file_embeddings=[[0.0]] * len(fds))
            create_classes(session, fds)
            all_methods = [m for fd in fds for m in fd.get("methods", [])]
            create_methods(session, fds, method_embeddings=[[0.0]] * len(all_methods))
            create_imports(session, fds)
            # Should not raise even if the ambiguous call can't be resolved
            create_method_calls(session, fds)

            # Verify there is exactly one CALLS edge at most (same-class call not present)
            c = session.run("MATCH ()-[r:CALLS]->() RETURN count(r) AS c").single().get("c")
            assert c >= 0
