from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def _get_driver_or_skip():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")
    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


def _init_tiny_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True)
    # user
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    # commit 1
    (repo / "a.txt").write_text("a1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    # commit 2
    (repo / "b.txt").write_text("b1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add b"], cwd=repo, check=True)


def test_git_history_live(tmp_path: Path):
    from src.analysis.git_analysis import (
        bulk_load_to_neo4j,
        create_dataframes,
        extract_git_history,
    )

    repo = tmp_path / "repo"
    _init_tiny_repo(repo)

    commits, file_changes = extract_git_history(repo, branch="HEAD", max_commits=None)
    commits_df, devs_df, files_df, file_changes_df = create_dataframes(commits, file_changes)

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            bulk_load_to_neo4j(
                commits_df,
                devs_df,
                files_df,
                file_changes_df,
                driver,
                database,
                skip_file_changes=False,
                file_changes_only=False,
            )
            # Assertions: basic counts > 0
            rec = session.run("MATCH (:Commit) RETURN count(*) AS c").single()
            assert rec and int(rec["c"]) >= 2
            rec = session.run("MATCH (:Developer) RETURN count(*) AS c").single()
            assert rec and int(rec["c"]) >= 1
            rec = session.run("MATCH (:File) RETURN count(*) AS c").single()
            assert rec and int(rec["c"]) >= 2
            rec = session.run(
                "MATCH (:Commit)-[:CHANGED]->(:FileVer)-[:OF_FILE]->(:File) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1
            # New: verify at least one PARENT edge exists (second commit points to first)
            rec = session.run("MATCH (:Commit)-[:PARENT]->(:Commit) RETURN count(*) AS c").single()
            assert rec and int(rec["c"]) >= 1
            # Verify CHANGED properties exist on some edge
            rec = session.run(
                """
                MATCH (:Commit)-[r:CHANGED]->(:FileVer)
                WITH collect(properties(r)) AS props
                RETURN size(props) AS n, any(p IN props WHERE p.changeType IS NOT NULL) AS hasType
                """
            ).single()
            assert rec and int(rec["n"]) >= 1 and bool(rec["hasType"]) is True
