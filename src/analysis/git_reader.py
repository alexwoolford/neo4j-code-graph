from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_git_history(
    repo_path: str | Path, branch: str, max_commits: int | None = None
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Extract git history using `git log` with streaming output."""
    logger.info("Extracting git history...")
    cmd: list[str] = [
        "git",
        "log",
        "--name-only",
        "--pretty=format:%H|%an|%ae|%ad|%s",
        "--date=iso",
        branch,
    ]
    if max_commits:
        cmd.append(f"-{max_commits}")

    start_time = time.time()
    process = subprocess.Popen(
        cmd, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    commits: list[dict[str, str]] = []
    file_changes: list[dict[str, str]] = []
    current_commit: dict[str, str] | None = None
    commits_processed = 0

    assert process.stdout is not None
    assert process.stderr is not None

    for line in process.stdout:
        line = line.rstrip("\n")
        if "|" in line and len(line.split("|")) >= 5:
            if current_commit:
                commits.append(current_commit)
                commits_processed += 1
            parts = line.split("|", 4)
            current_commit = {
                "sha": parts[0],
                "author_name": parts[1],
                "author_email": parts[2],
                "date": parts[3],
                "message": parts[4],
            }
        elif line.strip() and current_commit:
            file_changes.append({"sha": current_commit["sha"], "file_path": line.strip()})

    process.stdout.close()
    stderr = process.stderr.read()
    return_code = process.wait()

    if current_commit:
        commits.append(current_commit)
        commits_processed += 1

    if return_code != 0:
        raise Exception(f"Git log failed: {stderr}")

    total_time = time.time() - start_time
    logger.info(
        "Parsed %d commits and %d file changes in %.2fs (%.1f commits/sec)",
        commits_processed,
        len(file_changes),
        total_time,
        commits_processed / total_time if total_time > 0 else 0,
    )
    return commits, file_changes
