#!/usr/bin/env python3
"""HEAD-delta detection for incremental ingest (WP4 Phase 2).

``diff_changed_files`` runs ``git diff --name-status -M <since>..<head>`` and
buckets the changed Java files into added / modified / deleted / renamed.

``classify_ingest_mode`` (pure) and ``decide_ingest_mode`` (git-touching)
implement the fallback-to-full policy: any condition under which a HEAD-delta
patch could diverge from a fresh full ingest forces a full re-ingest, and the
reason is always logged.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_JAVA_SUFFIX = ".java"


def _is_java(path: str) -> bool:
    return path.endswith(_JAVA_SUFFIX)


def _run_git(repo_path: str | Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )


def get_head_sha(repo_path: str | Path) -> str | None:
    """Return the current HEAD commit sha, or None if not a git repo."""
    try:
        proc = _run_git(repo_path, ["rev-parse", "HEAD"])
        if proc.returncode != 0:
            return None
        sha = proc.stdout.strip()
        return sha or None
    except Exception:  # pragma: no cover - git unavailable
        return None


def is_ancestor(repo_path: str | Path, ancestor: str, descendant: str = "HEAD") -> bool:
    """True iff ``ancestor`` is an ancestor of ``descendant`` (git merge-base)."""
    try:
        proc = _run_git(repo_path, ["merge-base", "--is-ancestor", ancestor, descendant])
        return proc.returncode == 0
    except Exception:  # pragma: no cover
        return False


def is_shallow(repo_path: str | Path) -> bool:
    """True if the clone is shallow (a HEAD-delta could miss history)."""
    try:
        shallow_marker = Path(repo_path) / ".git" / "shallow"
        if shallow_marker.exists():
            return True
        proc = _run_git(repo_path, ["rev-parse", "--is-shallow-repository"])
        return proc.stdout.strip().lower() == "true"
    except Exception:  # pragma: no cover
        return False


def diff_changed_files(
    repo_path: str | Path, since_sha: str, head_sha: str = "HEAD"
) -> dict[str, list[Any]]:
    """Diff two revisions and bucket changed *.java files.

    Returns a dict with keys ``added``, ``modified``, ``deleted`` (lists of
    repo-relative paths) and ``renamed`` (list of ``(old_path, new_path)``
    tuples). Non-Java paths are ignored. Renames are detected with ``-M``.
    """
    result: dict[str, list[Any]] = {
        "added": [],
        "modified": [],
        "deleted": [],
        "renamed": [],
    }
    proc = _run_git(
        repo_path,
        ["diff", "--name-status", "-M", f"{since_sha}..{head_sha}"],
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git diff {since_sha}..{head_sha} failed: {proc.stderr.strip()}")

    for line in proc.stdout.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        code = parts[0]
        if code.startswith("R") and len(parts) == 3:
            old_path, new_path = parts[1], parts[2]
            # A rename is only interesting when either side is a Java file.
            if _is_java(old_path) or _is_java(new_path):
                result["renamed"].append((old_path, new_path))
            continue
        if code.startswith("C") and len(parts) == 3:
            # Copy: treat the new path as an addition.
            new_path = parts[2]
            if _is_java(new_path):
                result["added"].append(new_path)
            continue
        if len(parts) < 2:
            continue
        path = parts[1]
        if not _is_java(path):
            continue
        if code.startswith("A"):
            result["added"].append(path)
        elif code.startswith("M") or code.startswith("T"):
            result["modified"].append(path)
        elif code.startswith("D"):
            result["deleted"].append(path)
    return result


def changed_and_deleted(delta: dict[str, list[Any]]) -> tuple[list[str], list[str]]:
    """Flatten a delta into (files_to_extract, files_removed_at_head).

    - files_to_extract: added + modified + rename *new* paths (must be parsed
      and re-written).
    - files_removed_at_head: deleted + rename *old* paths (their footprint must
      be reconciled away).
    """
    to_extract: list[str] = []
    to_extract.extend(delta.get("added", []))
    to_extract.extend(delta.get("modified", []))
    removed: list[str] = list(delta.get("deleted", []))
    for old_path, new_path in delta.get("renamed", []):
        if _is_java(new_path):
            to_extract.append(new_path)
        if _is_java(old_path):
            removed.append(old_path)
    # De-dup while preserving order
    to_extract = list(dict.fromkeys(to_extract))
    removed = list(dict.fromkeys(removed))
    return to_extract, removed


def classify_ingest_mode(
    *,
    force_full: bool,
    has_hwm: bool,
    branch_changed: bool,
    schema_changed: bool,
    is_ancestor: bool,
    is_shallow: bool,
) -> tuple[str, str]:
    """Pure decision function: return ``(mode, reason)``.

    ``mode`` is ``"full"`` or ``"incremental"``. Any full-forcing condition wins
    and its human-readable reason is returned so callers can log it.
    """
    if force_full:
        return "full", "forced full re-ingest (--full)"
    if not has_hwm:
        return "full", "no prior successful ingest (no high-water mark)"
    if branch_changed:
        return "full", "branch changed since last successful ingest"
    if schema_changed:
        return "full", "SCHEMA_VERSION changed since last successful ingest"
    if is_shallow:
        return "full", "shallow clone (history may be incomplete)"
    if not is_ancestor:
        return "full", "last ingest sha is not an ancestor of HEAD (force-push/rebase)"
    return "incremental", "HEAD-delta since last successful ingest"


def decide_ingest_mode(
    repo_path: str | Path,
    last_ingest: dict[str, Any] | None,
    branch: str,
    schema_version: int,
    head_sha: str | None,
    force_full: bool = False,
) -> tuple[str, str]:
    """Combine the git probes with ``classify_ingest_mode`` and log the reason."""
    has_hwm = bool(last_ingest and last_ingest.get("head_sha"))
    since_sha = str(last_ingest.get("head_sha")) if last_ingest else ""
    stored_branch = last_ingest.get("branch") if last_ingest else None
    # branch is unknown-safe: only treat as changed when we have both values.
    branch_changed = bool(has_hwm and stored_branch is not None and stored_branch != branch)
    schema_changed = bool(
        has_hwm
        and last_ingest is not None
        and last_ingest.get("schema_version") not in (None, schema_version)
    )
    shallow = is_shallow(repo_path)
    ancestor_ok = is_ancestor(repo_path, since_sha) if has_hwm else False

    mode, reason = classify_ingest_mode(
        force_full=force_full,
        has_hwm=has_hwm,
        branch_changed=branch_changed,
        schema_changed=schema_changed,
        is_ancestor=ancestor_ok,
        is_shallow=shallow,
    )
    logger.info("Ingest mode decision: %s (%s)", mode, reason)
    return mode, reason
