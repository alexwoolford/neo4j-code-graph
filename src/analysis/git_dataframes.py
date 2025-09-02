from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def create_dataframes(
    commits: list[dict[str, str]], file_changes: list[dict[str, str]]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    logger.info("Creating pandas DataFrames...")
    commits_df = pd.DataFrame(commits)
    commits_df["date"] = pd.to_datetime(commits_df["date"], utc=True)

    # Parent SHAs are kept in commits_df["parents"]; bulk writer parses them to create PARENT edges.

    file_changes_df = pd.DataFrame(file_changes)
    developers_df = commits_df[["author_name", "author_email"]].drop_duplicates()
    developers_df = developers_df.rename(columns={"author_name": "name", "author_email": "email"})
    files_df = file_changes_df[["file_path"]].drop_duplicates()
    files_df = files_df.rename(columns={"file_path": "path"})

    logger.info(
        "Created DataFrames: %d commits, %d developers, %d files, %d file changes",
        len(commits_df),
        len(developers_df),
        len(files_df),
        len(file_changes_df),
    )
    # Attach parents_df to return signature by convention expansion in callers if needed
    # but maintain backward compatibility by returning four dataframes as before.
    # Callers needing parents can import from commits_df by re-parsing, or we can
    # later extend the function signature in a follow-up change if desired.
    return commits_df, developers_df, files_df, file_changes_df
