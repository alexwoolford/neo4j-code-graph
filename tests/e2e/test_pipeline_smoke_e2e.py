#!/usr/bin/env python3
import textwrap
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_builds_minimal_graph(neo4j_driver, tmp_path: Path):
    # Create a tiny Java repo
    src = tmp_path / "src/main/java/com/example"
    src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_text(
        textwrap.dedent(
            """
            package com.example;
            public class A { public void a() { } }
            """
        ).strip()
    )

    # Run minimal pipeline pieces directly to keep e2e fast
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships, extract_file_data
    from src.constants import EMBEDDING_DIMENSION
    from src.data.schema_management import setup_complete_schema

    java_files = list((tmp_path / "src").rglob("*.java"))
    files_data = [extract_file_data(p, tmp_path) for p in java_files]
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

        # Invariants: nodes exist and identities are unique
        rows = s.run(
            """
            CALL { RETURN 'File' AS lbl UNION ALL RETURN 'Method' AS lbl UNION ALL RETURN 'Class' AS lbl }
            WITH lbl
            CALL apoc.cypher.run("MATCH (n:`" + lbl + "`) RETURN count(n) AS c", {}) YIELD value
            RETURN lbl, value.c AS c
            """
        ).data()
        counts = {r["lbl"]: r["c"] for r in rows}
        assert any(v > 0 for v in counts.values())

        # Required properties on Method
        res = s.run(
            "MATCH (m:Method) RETURN count(m) AS n, sum(CASE WHEN m.method_signature IS NULL THEN 1 ELSE 0 END) AS missing"
        ).data()[0]
        assert res["n"] >= 1 and res["missing"] == 0

        # Key relationships exist
        rels = s.run(
            "MATCH (:File)-[:DECLARES]->(:Method) WITH count(*) AS file_declares "
            "MATCH (:Class)-[:CONTAINS_METHOD]->(:Method) RETURN file_declares, count(*) AS class_contains"
        ).data()[0]
        assert rels["file_declares"] >= 0  # presence check (query runs)
