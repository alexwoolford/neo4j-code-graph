from pathlib import Path

from git import Repo

from src.analysis.git_analysis import create_dataframes, extract_git_history


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_extract_git_history_end_to_end(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    repo = Repo.init(repo_dir)
    # Configure identity for commits
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Tester")
        cw.set_value("user", "email", "tester@example.com")

    f1 = repo_dir / "src" / "A.java"
    f2 = repo_dir / "src" / "B.java"

    _write(f1, "class A {}\n")
    repo.index.add([str(f1)])
    repo.index.commit("initial commit")

    _write(f2, "class B {}\n")
    repo.index.add([str(f2)])
    repo.index.commit("add B")

    _write(f1, "class A { void m() {} }\n")
    repo.index.add([str(f1)])
    repo.index.commit("modify A")

    # Use HEAD to be agnostic to default branch naming
    commits, file_changes = extract_git_history(str(repo_dir), "HEAD", max_commits=None)

    assert len(commits) >= 3
    assert any("initial commit" in c["message"] for c in commits)
    assert any(fc["file_path"].endswith("A.java") for fc in file_changes)
    assert any(fc["file_path"].endswith("B.java") for fc in file_changes)

    commits_df, developers_df, files_df, file_changes_df = create_dataframes(commits, file_changes)

    assert not commits_df.empty
    assert not developers_df.empty
    assert set(files_df.columns) == {"path"}
    # Ensure both files are registered
    paths = set(files_df["path"].tolist())
    assert "src/A.java" in paths and "src/B.java" in paths
