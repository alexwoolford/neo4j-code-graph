#!/usr/bin/env python3
"""
Git history loader for Neo4j using git log commands and bulk processing.
"""

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
from git import Repo

from src.utils.neo4j_utils import get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Load git history into Neo4j")

    # Import add_common_args - handle both script and module execution
    from src.utils.common import add_common_args

    add_common_args(parser)  # Adds Neo4j connection and logging args

    # Add git-specific arguments
    parser.add_argument("repo_url", help="URL or local path of the Git repository")
    parser.add_argument("--branch", default="master", help="Branch to process")
    parser.add_argument("--csv-export", help="Export to CSV files instead of Neo4j")
    parser.add_argument("--max-commits", type=int, help="Limit number of commits (for testing)")
    parser.add_argument(
        "--skip-file-changes",
        action="store_true",
        help="Skip loading file changes (for faster testing)",
    )
    parser.add_argument(
        "--file-changes-only",
        action="store_true",
        help="Only load file changes (assumes other data exists)",
    )
    return parser.parse_args()


from src.analysis.git_bulk_writer import bulk_load_to_neo4j
from src.analysis.git_dataframes import create_dataframes
from src.analysis.git_reader import extract_git_history


def export_to_csv(
    commits_df: pd.DataFrame,
    developers_df: pd.DataFrame,
    files_df: pd.DataFrame,
    file_changes_df: pd.DataFrame,
    output_dir: str | Path,
) -> None:
    """Export DataFrames to CSV files."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    logger.info(f"📁 Exporting to CSV files in {output_path}")

    commits_df.to_csv(output_path / "commits.csv", index=False)
    developers_df.to_csv(output_path / "developers.csv", index=False)
    files_df.to_csv(output_path / "files.csv", index=False)
    file_changes_df.to_csv(output_path / "file_changes.csv", index=False)

    logger.info("CSV export completed")


def load_history(
    repo_url: str,
    branch: str,
    uri: str,
    username: str,
    password: str,
    database: str | None = None,
    csv_export: str | Path | None = None,
    max_commits: int | None = None,
    skip_file_changes: bool = False,
    file_changes_only: bool = False,
) -> None:
    """Load git history using optimized approach."""
    # Check if repo_url is a local path or a URL
    repo_path = Path(repo_url)
    if repo_path.exists() and repo_path.is_dir():
        # Local path - use directly
        logger.info(f"📁 Using local repository: {repo_url}")
        repo = Repo(repo_url)
        tmpdir = None
        repo_dir = repo_url
    else:
        # URL - clone to temporary directory
        tmpdir = tempfile.mkdtemp()

        try:
            # Clone repository
            logger.info(f"📥 Cloning {repo_url}...")
            start_time = time.time()
            repo = Repo.clone_from(repo_url, tmpdir)
            clone_time = time.time() - start_time
            logger.info(f"Repository cloned in {clone_time:.2f}s")
            repo_dir = tmpdir
        except Exception:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
            raise

    try:
        # Handle branch checkout with fallback
        if branch:
            try:
                repo.git.checkout(branch)
                logger.info(f"Checked out branch: {branch}")
            except Exception as e:
                available_branches = [ref.name.split("/")[-1] for ref in repo.remotes.origin.refs]
                logger.warning(f"Branch '{branch}' not found. Available: {available_branches}")

                for fallback in ["main", "master", "dev", "develop", "HEAD"]:
                    if fallback in available_branches:
                        logger.info(f"Falling back to branch: {fallback}")
                        repo.git.checkout(fallback)
                        branch = fallback
                        break
                else:
                    logger.error(f"No suitable branch found. Error: {e}")
                    raise

        # Extract git history from the repository directory
        commits, file_changes = extract_git_history(repo_dir, branch, max_commits)

        # Create DataFrames
        commits_df, developers_df, files_df, file_changes_df = create_dataframes(
            commits, file_changes
        )

        # Export or load
        if csv_export:
            export_to_csv(commits_df, developers_df, files_df, file_changes_df, csv_export)
        else:
            # Import create_neo4j_driver - handle both script and module execution
            try:
                from utils.common import create_neo4j_driver
            except ImportError:
                from src.utils.common import create_neo4j_driver

            with create_neo4j_driver(uri, username, password) as driver:
                # Fail-fast: ensure constraints before writing
                try:
                    from src.data.schema_management import (  # type: ignore
                        ensure_constraints_exist_or_fail as _ensure,
                    )
                except Exception:
                    from src.data.schema_management import (  # type: ignore
                        ensure_constraints_exist_or_fail as _ensure,
                    )
                with driver.session(database=database) as _session:  # type: ignore[reportUnknownMemberType]
                    _ensure(_session)
                bulk_load_to_neo4j(
                    commits_df,
                    developers_df,
                    files_df,
                    file_changes_df,
                    driver,
                    database,
                    skip_file_changes,
                    file_changes_only,
                )

        logger.info("✅ Git history processing completed successfully")

    except Exception as e:
        logger.error(f"Error processing repository: {e}")
        raise
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> None:
    args = parse_args()

    # Setup logging using consistent helper
    from src.utils.common import setup_logging

    setup_logging(args.log_level, args.log_file)

    if args.csv_export:
        load_history(
            args.repo_url,
            args.branch,
            args.uri,
            args.username,
            args.password,
            args.database,
            args.csv_export,
            args.max_commits,
            args.skip_file_changes,
            args.file_changes_only,
        )
    else:
        try:
            from src.utils.common import create_neo4j_driver

            with create_neo4j_driver(args.uri, args.username, args.password) as _:
                logger.info(f"Connected to Neo4j at {args.uri}")
                load_history(
                    args.repo_url,
                    args.branch,
                    args.uri,
                    args.username,
                    args.password,
                    args.database,
                    None,
                    args.max_commits,
                    args.skip_file_changes,
                    args.file_changes_only,
                )
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
