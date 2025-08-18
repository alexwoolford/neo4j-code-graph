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
            "RETURN (SELECT count(*) FROM (MATCH (:Class) RETURN 1)) AS classes,"
            "       (SELECT count(*) FROM (MATCH (:Method) RETURN 1)) AS methods"
        ).data()[0]
        assert res["classes"] >= 1 and res["methods"] >= 2

        # Check CONTAINS_METHOD and DECLARES edges are present
        edges = s.run(
            "RETURN (SELECT count(*) FROM (MATCH (:Class)-[:CONTAINS_METHOD]->(:Method) RETURN 1)) AS cm,"
            "       (SELECT count(*) FROM (MATCH (:File)-[:DECLARES]->(:Method) RETURN 1)) AS fm"
        ).data()[0]
        assert edges["cm"] >= 1 and edges["fm"] >= 2
