from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def bulk_load_to_neo4j(
    commits_df: pd.DataFrame,
    developers_df: pd.DataFrame,
    files_df: pd.DataFrame,
    file_changes_df: pd.DataFrame,
    driver: Any,
    database: str,
    skip_file_changes: bool = False,
    file_changes_only: bool = False,
) -> None:
    logger.info("Loading data to Neo4j using bulk operations...")
    wall_start = time.monotonic()

    def execute_with_retry(
        session: Any, query: str, params: dict[str, Any], description: str, max_retries: int = 3
    ) -> Any:
        for attempt in range(max_retries):
            try:
                session.run(query, params)
                return session
            except Exception as e:  # pragma: no cover - retry path
                logger.warning("Attempt %d failed for %s: %s", attempt + 1, description, e)
                if attempt == max_retries - 1:
                    raise
                try:
                    session.close()
                finally:
                    session = driver.session(database=database)
        return session

    session = driver.session(database=database)
    try:
        if not file_changes_only:
            stage_start = time.monotonic()
            logger.info("Loading %d developers...", len(developers_df))
            developers_data = developers_df.to_dict("records")
            session = execute_with_retry(
                session,
                """
                UNWIND $developers AS dev
                MERGE (d:Developer {email: dev.email})
                SET d.name = dev.name
                """,
                {"developers": developers_data},
                "developers",
            )
            logger.info("Developers loaded in %.2fs", time.monotonic() - stage_start)

        stage_start = time.monotonic()
        logger.info("Loading %d commits...", len(commits_df))
        commits_data = commits_df.to_dict("records")
        for commit in commits_data:
            commit["date"] = commit["date"].to_pydatetime()

        commit_batch_size = 5000
        for i in range(0, len(commits_data), commit_batch_size):
            batch = commits_data[i : i + commit_batch_size]
            session = execute_with_retry(
                session,
                """
                UNWIND $commits AS commit
                MERGE (c:Commit {sha: commit.sha})
                SET c.date = commit.date,
                    c.message = commit.message
                WITH c, commit
                MERGE (d:Developer {email: commit.author_email})
                MERGE (d)-[:AUTHORED]->(c)
                """,
                {"commits": batch},
                f"commits batch {i // commit_batch_size + 1}",
            )
            logger.info(
                "Loaded %d/%d commits",
                min(i + commit_batch_size, len(commits_data)),
                len(commits_data),
            )
        logger.info("Commits + AUTHORED edges loaded in %.2fs", time.monotonic() - stage_start)

        # Create PARENT edges using parent SHAs parsed by git_reader (space-separated in 'parents').
        parent_edges: list[dict[str, str]] = []
        for commit in commits_data:
            parents_field = commit.get("parents")
            if isinstance(parents_field, str) and parents_field.strip():
                for parent_sha in parents_field.strip().split(" "):
                    if parent_sha:
                        parent_edges.append({"sha": commit["sha"], "parent": parent_sha})

        if parent_edges:
            stage_start = time.monotonic()
            logger.info("Writing %d PARENT edges...", len(parent_edges))
            batch_size = 10000
            for i in range(0, len(parent_edges), batch_size):
                batch = parent_edges[i : i + batch_size]
                session = execute_with_retry(
                    session,
                    """
                    UNWIND $edges AS e
                    MERGE (c:Commit {sha: e.sha})
                    MERGE (p:Commit {sha: e.parent})
                    MERGE (c)-[:PARENT]->(p)
                    """,
                    {"edges": batch},
                    f"parent edges batch {i // batch_size + 1}",
                )
            logger.info("PARENT edges written in %.2fs", time.monotonic() - stage_start)

        stage_start = time.monotonic()
        logger.info("Loading %d files...", len(files_df))
        files_data = files_df.to_dict("records")
        session = execute_with_retry(
            session,
            """
            UNWIND $files AS file
            MERGE (f:File {path: file.path})
            """,
            {"files": files_data},
            "files",
        )
        logger.info("Files loaded in %.2fs", time.monotonic() - stage_start)

        if skip_file_changes:
            logger.info("Skipping file changes loading as requested")
            return

        logger.info("Loading %d file changes with bulk operations...", len(file_changes_df))
        # Coerce additions/deletions to integers and replace NaN with None to avoid float NaN in Neo4j
        import math  # local import to avoid module-level dependency

        def _as_int(val: Any) -> int | None:
            if val is None:
                return None
            try:
                # Handle pandas/numpy NaN
                if isinstance(val, float) and math.isnan(val):
                    return None
                return int(val)
            except Exception:
                return None

        raw_records: list[dict[str, Any]] = file_changes_df.to_dict("records")  # type: ignore[assignment]
        file_changes_data: list[dict[str, Any]] = []
        for rec in raw_records:
            rec["additions"] = _as_int(rec.get("additions"))
            rec["deletions"] = _as_int(rec.get("deletions"))
            file_changes_data.append(rec)
        batch_size = 10000
        total_batches = (len(file_changes_data) + batch_size - 1) // batch_size
        logger.info("Processing in %d batches of %s records each", total_batches, f"{batch_size:,}")
        from tqdm import tqdm  # local import

        total_stage_start = time.monotonic()
        for i in tqdm(
            range(0, len(file_changes_data), batch_size),
            total=total_batches,
            desc="Git file changes",
        ):
            batch_num = i // batch_size + 1
            batch = file_changes_data[i : i + batch_size]
            step_start = time.monotonic()
            # Step 1: Create FileVer nodes (fast due to unique constraint)
            session = execute_with_retry(
                session,
                """
                UNWIND $changes AS change
                MERGE (fv:FileVer {sha: change.sha, path: change.file_path})
                """,
                {"changes": batch},
                f"FileVer nodes batch {batch_num}",
            )
            t_filever = time.monotonic() - step_start

            # Step 2: Create CHANGED relationships (use CREATE for performance)
            step2_start = time.monotonic()
            session = execute_with_retry(
                session,
                """
                UNWIND $changes AS change
                MATCH (c:Commit {sha: change.sha})
                MATCH (fv:FileVer {sha: change.sha, path: change.file_path})
                CREATE (c)-[rel:CHANGED]->(fv)
                SET rel.change_type = change.change_type,
                    rel.additions = change.additions,
                    rel.deletions = change.deletions,
                    rel.renamed_from = change.renamed_from
                """,
                {"changes": batch},
                f"CHANGED relationships batch {batch_num}",
            )
            t_changed = time.monotonic() - step2_start

            # Step 3: Create OF_FILE relationships (use CREATE for performance)
            step3_start = time.monotonic()
            session = execute_with_retry(
                session,
                """
                UNWIND $changes AS change
                MATCH (f:File {path: change.file_path})
                MATCH (fv:FileVer {sha: change.sha, path: change.file_path})
                CREATE (fv)-[:OF_FILE]->(f)
                """,
                {"changes": batch},
                f"OF_FILE relationships batch {batch_num}",
            )
            t_offile = time.monotonic() - step3_start
            t_batch = time.monotonic() - step_start
            logger.info(
                "Batch %d/%d timings: FileVer=%.2fs, CHANGED=%.2fs, OF_FILE=%.2fs, total=%.2fs",
                batch_num,
                total_batches,
                t_filever,
                t_changed,
                t_offile,
                t_batch,
            )
        logger.info("All file changes processed in %.2fs", time.monotonic() - total_stage_start)
    finally:
        session.close()
    logger.info("Git bulk load complete in %.2fs", time.monotonic() - wall_start)
