from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def extract_git_history(
    repo_path: str | Path, branch: str, max_commits: int | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract git history using `git log` with streaming output."""
    logger.info("Extracting git history...")
    cmd: list[str] = [
        "git",
        "log",
        "--name-only",
        # Include parent SHAs (%P) so we can materialize PARENT edges later.
        # Place %P before %s so the commit message remains the trailing field.
        "--pretty=format:%H|%an|%ae|%ad|%P|%s",
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
        # Expect at least 6 fields now: sha|author|email|date|parents|message
        if "|" in line and len(line.split("|")) >= 6:
            if current_commit:
                commits.append(current_commit)
                commits_processed += 1
            # Split into 6 parts so message remains intact even if it contains '|'
            parts = line.split("|", 5)
            current_commit = {
                "sha": parts[0],
                "author_name": parts[1],
                "author_email": parts[2],
                "date": parts[3],
                # Parents are space-separated SHAs; may be empty for root commits
                "parents": parts[4],
                "message": parts[5],
            }
        elif line.strip() and current_commit:
            # We no longer rely on this name-only list for properties; keep minimal capture
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

    # Enrich file changes with changeType/additions/deletions/renamedFrom using git show per commit.
    enriched_changes: list[dict[str, str | int | None]] = []
    for c in commits:
        sha = c["sha"]
        status_map: dict[str, dict[str, str | int | None]] = {}
        # Pass 1: change types and renames
        ns_cmd = [
            "git",
            "show",
            "--name-status",
            "-M",
            "--format=",
            sha,
        ]
        proc1 = subprocess.Popen(
            ns_cmd, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        assert proc1.stdout is not None
        for ln in proc1.stdout:
            ln = ln.rstrip("\n")
            if not ln:
                continue
            parts = ln.split("\t")
            if not parts:
                continue
            code = parts[0]
            if code.startswith("R") and len(parts) >= 3:
                old_path = parts[1]
                new_path = parts[2]
                status_map[new_path] = {
                    "changeType": "renamed",
                    "renamedFrom": old_path,
                    "additions": None,
                    "deletions": None,
                }
            elif code.startswith("A") and len(parts) >= 2:
                path = parts[1]
                status_map[path] = {
                    "changeType": "added",
                    "renamedFrom": None,
                    "additions": None,
                    "deletions": None,
                }
            elif code.startswith("M") and len(parts) >= 2:
                path = parts[1]
                status_map[path] = {
                    "changeType": "modified",
                    "renamedFrom": None,
                    "additions": None,
                    "deletions": None,
                }
            elif code.startswith("D") and len(parts) >= 2:
                path = parts[1]
                status_map[path] = {
                    "changeType": "deleted",
                    "renamedFrom": None,
                    "additions": None,
                    "deletions": None,
                }

        # Pass 2: line counts
        num_cmd = [
            "git",
            "show",
            "--numstat",
            "--format=",
            sha,
        ]
        proc2 = subprocess.Popen(
            num_cmd, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        assert proc2.stdout is not None
        for ln in proc2.stdout:
            ln = ln.rstrip("\n")
            if not ln:
                continue
            parts = ln.split("\t")
            if len(parts) == 3 and (
                (parts[0].isdigit() or parts[0] == "-") and (parts[1].isdigit() or parts[1] == "-")
            ):
                add_s, del_s, path = parts
                adds = int(add_s) if add_s.isdigit() else None
                dels = int(del_s) if del_s.isdigit() else None
                if path not in status_map:
                    status_map[path] = {
                        "changeType": None,
                        "renamedFrom": None,
                        "additions": adds,
                        "deletions": dels,
                    }
                else:
                    status_map[path]["additions"] = adds
                    status_map[path]["deletions"] = dels
        # collect
        for path, props in status_map.items():
            enriched_changes.append(
                {
                    "sha": sha,
                    "file_path": path,
                    "changeType": props.get("changeType"),
                    "additions": props.get("additions"),
                    "deletions": props.get("deletions"),
                    "renamedFrom": props.get("renamedFrom"),
                }
            )

    return commits, enriched_changes
