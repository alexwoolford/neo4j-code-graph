"""Re-running git-history ingest and coupling must not change the graph.

Guards the WP4 Phase-0 idempotency fixes: CHANGED/OF_FILE are MERGEd (not
CREATEd) and CO_CHANGED is rebuilt from scratch on every write run, so a
second identical run yields byte-identical counts and support values.
"""

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


def _init_coupled_repo(repo: Path) -> None:
    """Three commits, each touching a.txt and b.txt together (support=3)."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    for i in range(3):
        (repo / "a.txt").write_text(f"a{i}\n", encoding="utf-8")
        (repo / "b.txt").write_text(f"b{i}\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", f"change {i}"], cwd=repo, check=True)


def _ingest(repo: Path, driver, database: str) -> None:
    from src.analysis.git_analysis import (
        bulk_load_to_neo4j,
        create_dataframes,
        extract_git_history,
    )

    commits, file_changes = extract_git_history(repo, branch="HEAD", max_commits=None)
    commits_df, devs_df, files_df, file_changes_df = create_dataframes(commits, file_changes)
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


def _graph_counts(session) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, query in {
        "commits": "MATCH (:Commit) RETURN count(*) AS c",
        "changed": "MATCH ()-[r:CHANGED]->() RETURN count(r) AS c",
        "of_file": "MATCH ()-[r:OF_FILE]->() RETURN count(r) AS c",
        "file_vers": "MATCH (:FileVer) RETURN count(*) AS c",
    }.items():
        rec = session.run(query).single()
        out[key] = int(rec["c"]) if rec else -1
    return out


def _co_changed_rows(session) -> list[tuple[str, str, int]]:
    result = session.run(
        """
        MATCH (f1:File)-[cc:CO_CHANGED]->(f2:File)
        RETURN f1.path AS p1, f2.path AS p2, cc.support AS support
        ORDER BY p1, p2
        """
    )
    return [(r["p1"], r["p2"], int(r["support"])) for r in result]


def test_double_ingest_and_coupling_idempotent_live(tmp_path: Path):
    from src.analysis.temporal_analysis import run_coupling

    repo = tmp_path / "repo"
    _init_coupled_repo(repo)

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()

        _ingest(repo, driver, database)
        run_coupling(driver, database, min_support=2, confidence_threshold=0.0, write=True)
        with driver.session(database=database) as session:
            counts_first = _graph_counts(session)
            coupled_first = _co_changed_rows(session)

        # Sanity: the fixture actually produced history and coupling evidence
        assert counts_first["commits"] == 3
        assert counts_first["changed"] == 6  # 3 commits x 2 files
        assert coupled_first, "expected at least one CO_CHANGED pair"
        assert all(support == 3 for _, _, support in coupled_first)

        # Second identical run must be a no-op for every count and support value
        _ingest(repo, driver, database)
        run_coupling(driver, database, min_support=2, confidence_threshold=0.0, write=True)
        with driver.session(database=database) as session:
            counts_second = _graph_counts(session)
            coupled_second = _co_changed_rows(session)

        assert counts_second == counts_first
        assert coupled_second == coupled_first
