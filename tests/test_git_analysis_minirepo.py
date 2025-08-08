#!/usr/bin/env python3

import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
def test_extract_git_history_from_minirepo(tmp_path: Path):
    # Initialize a tiny git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)

    # Create a file and commit
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    # Second commit
    (repo / "src.py").write_text("print('ok')\n")
    subprocess.run(["git", "add", "src.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add src"], cwd=repo, check=True)

    from src.analysis.git_analysis import create_dataframes, extract_git_history

    commits, changes = extract_git_history(str(repo), "HEAD", max_commits=10)
    assert len(commits) >= 1
    assert any(c["message"] for c in commits)
    assert any(ch["file_path"] for ch in changes)

    commits_df, devs_df, files_df, changes_df = create_dataframes(commits, changes)
    assert not commits_df.empty
    assert not files_df.empty
    assert not changes_df.empty
