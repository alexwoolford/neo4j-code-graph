#!/usr/bin/env python3
"""Ingest provenance / incremental high-water mark (WP4 Phase 1).

Each pipeline run records an :Ingest node linked to a :Repository node::

    (:Repository {url})-[:HAS_INGEST]->(:Ingest {
        id, head_sha, branch, mode, tool_version, schema_version,
        status, started_at, finished_at
    })

The most recent ``status='success'`` :Ingest for a (repo, branch) pair is the
*high-water mark* (HWM): the commit the graph was last brought up to date with.
Incremental ingest diffs HEAD against that sha. The HWM only advances when a run
finishes with ``status='success'`` — a crashed run leaves the previous HWM in
place, so the next run safely re-processes the same delta (Phases 3–5 are
idempotent).
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def tool_version() -> str:
    """Best-effort package version string stamped on each :Ingest node."""
    try:
        from importlib.metadata import version as _version

        return str(_version("neo4j-code-graph"))
    except Exception:  # pragma: no cover - metadata missing in editable/dev trees
        try:
            import tomllib

            root = Path(__file__).resolve().parents[2]
            data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
            return str(data.get("project", {}).get("version", "0.0.0"))
        except Exception:
            return "0.0.0"


def normalize_repo_url(repo_url: str) -> str:
    """Canonicalize a repo identifier so the same repo maps to one :Repository.

    - For remote URLs: strip a trailing ``.git`` and trailing slashes.
    - For local paths: prefer the ``origin`` remote URL when the directory is a
      git repo with one; otherwise fall back to the absolute path.
    """
    raw = (repo_url or "").strip()
    if not raw:
        return raw

    candidate = Path(raw)
    if candidate.exists() and candidate.is_dir():
        try:
            from git import Repo  # local import; git may be unavailable in some envs

            repo = Repo(str(candidate))
            origin = None
            try:
                origin = repo.remotes.origin.url
            except Exception:
                origin = None
            if origin:
                raw = str(origin)
            else:
                return str(candidate.resolve())
        except Exception:
            return str(candidate.resolve())

    # Normalize remote URL form
    raw = raw.rstrip("/")
    raw = re.sub(r"\.git$", "", raw)
    return raw


def record_ingest_start(
    session: Any,
    repo_url: str,
    branch: str,
    head_sha: str | None,
    mode: str,
    tool_version: str,
    schema_version: int,
) -> str:
    """Create a ``status='running'`` :Ingest node and return its id.

    The id is a random uuid4 hex (runtime code, not a reproducible workflow
    artifact), guaranteeing uniqueness without depending on wall-clock time.
    """
    ingest_id = uuid.uuid4().hex
    session.run(
        """
        MERGE (r:Repository {url: $repo_url})
        CREATE (i:Ingest {
            id: $id,
            head_sha: $head_sha,
            branch: $branch,
            mode: $mode,
            tool_version: $tool_version,
            schema_version: $schema_version,
            status: 'running',
            started_at: datetime()
        })
        MERGE (r)-[:HAS_INGEST]->(i)
        """,
        repo_url=repo_url,
        id=ingest_id,
        head_sha=head_sha,
        branch=branch,
        mode=mode,
        tool_version=tool_version,
        schema_version=int(schema_version),
    )
    logger.info(
        "Recorded ingest start id=%s repo=%s branch=%s mode=%s head=%s",
        ingest_id,
        repo_url,
        branch,
        mode,
        head_sha,
    )
    return ingest_id


def record_ingest_finish(session: Any, ingest_id: str, status: str) -> None:
    """Stamp ``finished_at`` and terminal ``status`` on an :Ingest node."""
    session.run(
        """
        MATCH (i:Ingest {id: $id})
        SET i.finished_at = datetime(), i.status = $status
        """,
        id=ingest_id,
        status=status,
    )
    logger.info("Recorded ingest finish id=%s status=%s", ingest_id, status)


def get_last_successful_ingest(session: Any, repo_url: str, branch: str) -> dict[str, Any] | None:
    """Return the latest successful :Ingest for (repo, branch), or None.

    Ordered by ``finished_at`` descending so the most recently completed
    successful run wins. Returns head_sha / schema_version / tool_version / id.
    """
    rec = session.run(
        """
        MATCH (r:Repository {url: $repo_url})-[:HAS_INGEST]->(i:Ingest)
        WHERE i.branch = $branch AND i.status = 'success'
        RETURN i.head_sha AS head_sha,
               i.schema_version AS schema_version,
               i.tool_version AS tool_version,
               i.id AS id
        ORDER BY i.finished_at DESC
        LIMIT 1
        """,
        repo_url=repo_url,
        branch=branch,
    ).single()
    if rec is None:
        return None
    return {
        "head_sha": rec.get("head_sha"),
        "schema_version": rec.get("schema_version"),
        "tool_version": rec.get("tool_version"),
        "id": rec.get("id"),
    }
