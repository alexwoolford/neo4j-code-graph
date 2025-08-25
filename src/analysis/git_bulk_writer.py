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

    def execute_with_retry(
        session, query: str, params: dict, description: str, max_retries: int = 3
    ):
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

        if skip_file_changes:
            logger.info("Skipping file changes loading as requested")
            return

        logger.info("Loading %d file changes with bulk operations...", len(file_changes_df))
        file_changes_data = file_changes_df.to_dict("records")
        batch_size = 10000
        total_batches = (len(file_changes_data) + batch_size - 1) // batch_size
        logger.info("Processing in %d batches of %s records each", total_batches, f"{batch_size:,}")
        # start_time kept out to avoid unused var
        from tqdm import tqdm  # local import

        for i in tqdm(
            range(0, len(file_changes_data), batch_size),
            total=total_batches,
            desc="Git file changes",
        ):
            # batch_start intentionally omitted to avoid unused var
            batch_num = i // batch_size + 1
            batch = file_changes_data[i : i + batch_size]
            step_start = time.time()
            session = execute_with_retry(
                session,
                """
                UNWIND $changes AS change
                MATCH (c:Commit {sha: change.sha})
                MATCH (f:File {path: change.file_path})
                MERGE (fv:FileVer {sha: change.sha, path: change.file_path})
                MERGE (c)-[:CHANGED]->(fv)
                MERGE (fv)-[:OF_FILE]->(f)
                """,
                {"changes": batch},
                f"FileVer creation and relationships batch {batch_num}",
            )
            _ = time.time() - step_start
            # keep timings minimal to avoid unused variables
            if batch_num < total_batches:
                time.sleep(0.1)
    finally:
        session.close()
