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

    # Enrich file changes in a single streaming pass over git log output.
    enriched_changes: list[dict[str, str | int | None]] = []
    log_cmd = [
        "git",
        "log",
        "--no-color",
        "--date=iso",
        "--pretty=format:__C__|%H",
        "--name-status",
        "-M",
        "--numstat",
        branch,
    ]
    proc = subprocess.Popen(
        log_cmd, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    cur_sha: str | None = None
    status_map: dict[str, dict[str, str | int | None]] = {}

    def _flush() -> None:
        nonlocal status_map, cur_sha
        if cur_sha and status_map:
            for path, props in status_map.items():
                enriched_changes.append(
                    {
                        "sha": cur_sha,
                        "file_path": path,
                        "change_type": props.get("change_type"),
                        "additions": props.get("additions"),
                        "deletions": props.get("deletions"),
                        "renamed_from": props.get("renamed_from"),
                    }
                )
        status_map = {}

    for ln in proc.stdout:
        ln = ln.rstrip("\n")
        if not ln:
            continue
        if ln.startswith("__C__|"):
            # new commit boundary
            _flush()
            cur_sha = ln.split("|", 1)[1]
            continue
        # name-status line
        if "\t" in ln:
            parts = ln.split("\t")
            if len(parts) == 2:
                code, path = parts
                if code.startswith("R"):
                    # rename lines are emitted as Rxx\told\tnew in other forms; handle conservatively when 2 cols
                    status_map[path] = {
                        "change_type": "renamed",
                        "renamed_from": None,
                        "additions": None,
                        "deletions": None,
                    }
                elif code.startswith("A"):
                    status_map[path] = {
                        "change_type": "added",
                        "renamed_from": None,
                        "additions": None,
                        "deletions": None,
                    }
                elif code.startswith("M"):
                    status_map[path] = {
                        "change_type": "modified",
                        "renamed_from": None,
                        "additions": None,
                        "deletions": None,
                    }
                elif code.startswith("D"):
                    status_map[path] = {
                        "change_type": "deleted",
                        "renamed_from": None,
                        "additions": None,
                        "deletions": None,
                    }
            elif len(parts) == 3 and parts[0].startswith("R"):
                _, old_path, new_path = parts
                status_map[new_path] = {
                    "change_type": "renamed",
                    "renamed_from": old_path,
                    "additions": None,
                    "deletions": None,
                }
            else:
                # maybe a numstat line (adds\tdels\tpath)
                if len(parts) == 3:
                    add_s, del_s, path = parts
                    if (add_s.isdigit() or add_s == "-") and (del_s.isdigit() or del_s == "-"):
                        adds = int(add_s) if add_s.isdigit() else None
                        dels = int(del_s) if del_s.isdigit() else None
                        if path not in status_map:
                            status_map[path] = {
                                "change_type": None,
                                "renamed_from": None,
                                "additions": adds,
                                "deletions": dels,
                            }
                        else:
                            status_map[path]["additions"] = adds
                            status_map[path]["deletions"] = dels
        else:
            # non-tabbed line; ignore
            pass
    _flush()

    return commits, enriched_changes
