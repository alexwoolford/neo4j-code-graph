#!/usr/bin/env python3

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

import src.pipeline.tasks.db_tasks as tasks


@pytest.mark.integration
def test_setup_schema_and_cleanup_integration(neo4j_driver: Any) -> None:
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    pwd = os.environ.get("NEO4J_PASSWORD")
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    assert uri and user and pwd

    # Call task functions directly (no Prefect engine) to avoid ephemeral server in CI
    tasks.setup_schema_task.fn(uri, user, pwd, db)
    tasks.selective_cleanup_task.fn(uri, user, pwd, db)

    # Sanity: SHOW CONSTRAINTS should return without error
    with neo4j_driver.session(database=db) as s:  # type: ignore[reportUnknownMemberType]
        s.run("SHOW CONSTRAINTS").consume()  # type: ignore[reportUnknownMemberType]


@pytest.mark.integration
def test_git_history_task_imports_minimal_repo(neo4j_driver: Any) -> None:
    from git import Repo  # type: ignore

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    pwd = os.environ.get("NEO4J_PASSWORD")
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    assert uri and user and pwd

    tmpdir = tempfile.mkdtemp(prefix="cg_repo_")
    repo = Repo.init(tmpdir)
    p = Path(tmpdir) / "README.md"
    p.write_text("hello\n")
    repo.index.add([str(p)])  # type: ignore[arg-type]
    repo.index.commit("init")

    tasks.git_history_task.fn(str(tmpdir), uri, user, pwd, db)

    with neo4j_driver.session(database=db) as s:  # type: ignore[reportUnknownMemberType]
        res = s.run("MATCH (c:Commit) RETURN count(c) AS n").single()  # type: ignore[reportUnknownMemberType]
        assert res is not None and int(res[0]) >= 1
