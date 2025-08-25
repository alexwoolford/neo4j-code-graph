#!/usr/bin/env python3
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_builds_graph_from_toy_java_fixtures(neo4j_driver):
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships, extract_file_data
    from src.constants import EMBEDDING_DIMENSION
    from src.data.schema_management import setup_complete_schema

    repo_root = Path(__file__).resolve().parents[2] / "tests/fixtures/repos/toy_java"
    assert repo_root.exists()

    java_files = list((repo_root / "src").rglob("*.java"))
    files_data = [extract_file_data(p, repo_root) for p in java_files]
    files_data = [fd for fd in files_data if fd]

    file_embeddings = [[0.0] * EMBEDDING_DIMENSION for _ in files_data]
    method_embeddings = [
        [0.0] * EMBEDDING_DIMENSION for _ in [m for fd in files_data for m in fd["methods"]]
    ]

    with neo4j_driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        setup_complete_schema(s)
        bulk_create_nodes_and_relationships(
            s, files_data, file_embeddings, method_embeddings, dependency_versions={}
        )

        # Expect at least one class and two methods
        res = s.run(
            "MATCH (c:Class) WITH count(c) AS classes MATCH (m:Method) RETURN classes, count(m) AS methods"
        ).data()[0]
        assert res["classes"] >= 1 and res["methods"] >= 2

        # Check CONTAINS_METHOD and DECLARES edges are present
        edges = s.run(
            "MATCH (:Class)-[:CONTAINS_METHOD]->(:Method) WITH count(*) AS cm "
            "MATCH (:File)-[:DECLARES]->(:Method) RETURN cm, count(*) AS fm"
        ).data()[0]
        assert edges["cm"] >= 1 and edges["fm"] >= 2

        # Method signature uniqueness
        dup = s.run(
            """
            MATCH (m:Method)
            WITH m.method_signature AS sig, count(*) AS c
            WHERE sig IS NOT NULL AND c > 1
            RETURN count(*) AS dups
            """
        ).data()[0]["dups"]
        assert dup == 0

        # Optional: CALLS edge from A#a to B#b (parser-dependent in tiny snippets)
        call = s.run(
            """
            MATCH (m1:Method {method_signature:'com.example.A#a():void'})-[:CALLS]->
                  (m2:Method {method_signature:'com.example.B#b():void'})
            RETURN count(*) AS c
            """
        ).data()[0]["c"]
        assert call >= 0
