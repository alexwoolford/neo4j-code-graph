#!/usr/bin/env python3

from __future__ import annotations

import os
from typing import Any

import pytest

import src.pipeline.tasks.db_tasks as tasks


def _gds_available() -> bool:
    try:
        from graphdatascience import GraphDataScience  # type: ignore

        uri = os.environ.get("NEO4J_URI")
        user = os.environ.get("NEO4J_USERNAME")
        pwd = os.environ.get("NEO4J_PASSWORD")
        db = os.environ.get("NEO4J_DATABASE", "neo4j")
        if not (uri and user and pwd):
            return False
        gds = GraphDataScience(uri, auth=(user, pwd), database=db, arrow=False)
        try:
            gds.run_cypher("RETURN 1")
            return True
        finally:
            gds.close()
    except Exception:
        return False


@pytest.mark.integration
def test_similarity_and_louvain_tasks_integration(neo4j_driver: Any) -> None:
    if not _gds_available():
        pytest.skip("GDS not available in environment")

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    pwd = os.environ.get("NEO4J_PASSWORD")
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    assert uri and user and pwd

    # Avoid Prefect ephemeral server in CI: call task functions directly
    tasks.similarity_task.fn(uri, user, pwd, db)
    tasks.louvain_task.fn(uri, user, pwd, db)


@pytest.mark.integration
def test_centrality_task_integration(neo4j_driver: Any) -> None:
    if not _gds_available():
        pytest.skip("GDS not available in environment")

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    pwd = os.environ.get("NEO4J_PASSWORD")
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    assert uri and user and pwd

    tasks.centrality_task.fn(uri, user, pwd, db)
