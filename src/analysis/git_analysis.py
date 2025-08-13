#!/usr/bin/env python3
"""
Git history loader for Neo4j using git log commands and bulk processing.
"""

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
from git import Repo

try:
    # Try absolute import when called from CLI wrapper
    from utils.neo4j_utils import get_neo4j_config
except ImportError:
    # Fallback to relative import when used as module
    from ..utils.neo4j_utils import get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Load git history into Neo4j")

    # Import add_common_args - handle both script and module execution
    try:
        from utils.common import add_common_args
    except ImportError:
        from ..utils.common import add_common_args

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


def extract_git_history(
    repo_path: str | Path, branch: str, max_commits: int | None = None
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Extract git history using git log commands."""
    logger.info("🚀 Extracting git history...")

    # Build git log command
    cmd = [
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

    # Execute git log with incremental output processing
    logger.info("Running git log command...")
    process = subprocess.Popen(
        cmd,
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    commits: list[dict[str, str]] = []
    file_changes: list[dict[str, str]] = []
    current_commit: dict[str, str] | None = None
    commits_processed: int = 0

    # Ensure pipes are present for type checkers
    assert process.stdout is not None
    assert process.stderr is not None

    # Process stdout line by line as it arrives
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

    # Finalize processing
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


def create_dataframes(
    commits: list[dict[str, str]], file_changes: list[dict[str, str]]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Convert extracted data to pandas DataFrames for efficient processing."""
    logger.info("Creating pandas DataFrames...")

    # Create commits DataFrame
    commits_df = pd.DataFrame(commits)
    commits_df["date"] = pd.to_datetime(commits_df["date"], utc=True)

    # Create file changes DataFrame
    file_changes_df = pd.DataFrame(file_changes)

    # Create developers DataFrame (unique developers)
    developers_df = commits_df[["author_name", "author_email"]].drop_duplicates()
    developers_df = developers_df.rename(columns={"author_name": "name", "author_email": "email"})

    # Create files DataFrame (unique files)
    files_df = file_changes_df[["file_path"]].drop_duplicates()
    files_df = files_df.rename(columns={"file_path": "path"})

    logger.info(
        f"Created DataFrames: {len(commits_df)} commits, {len(developers_df)} developers, "
        f"{len(files_df)} files, {len(file_changes_df)} file changes"
    )

    return commits_df, developers_df, files_df, file_changes_df


def bulk_load_to_neo4j(
    commits_df: pd.DataFrame,
    developers_df: pd.DataFrame,
    files_df: pd.DataFrame,
    file_changes_df: pd.DataFrame,
    driver,
    database: str,
    skip_file_changes: bool = False,
    file_changes_only: bool = False,
) -> None:
    """Load data to Neo4j using efficient bulk operations with resilience."""
    logger.info("💾 Loading data to Neo4j using bulk operations...")

    def execute_with_retry(
        session, query: str, params: dict, description: str, max_retries: int = 3
    ):
        """Execute query with retry logic and refresh the session on failure."""
        for attempt in range(max_retries):
            try:
                session.run(query, params)
                return session
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {description}: {e}")
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
            # Note: Schema constraints and indexes are now managed centrally by schema_management.py
            # They should be created via the schema setup step of the pipeline

            # Load developers
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

        # Load commits in smaller batches
        logger.info("Loading %d commits...", len(commits_df))
        commits_data = commits_df.to_dict("records")
        for commit in commits_data:
            # Use native datetime objects so Neo4j stores the value as a
            # DateTime instead of a plain string
            commit["date"] = commit["date"].to_pydatetime()

        commit_batch_size = 5000  # Smaller batches for better reliability
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

        # Load files
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

        # Skip file changes if requested
        if skip_file_changes:
            logger.info("⏭️  Skipping file changes loading as requested")
            return

        # Load file changes with sustainable bulk operations
        logger.info("🚀 Loading %d file changes with bulk operations...", len(file_changes_df))
        file_changes_data = file_changes_df.to_dict("records")

        # Use conservative batches to avoid overwhelming the database
        batch_size = 10000  # Conservative size that won't crash the database
        total_batches = (len(file_changes_data) + batch_size - 1) // batch_size

        logger.info(
            "📦 Processing in %d batches of %s records each", total_batches, f"{batch_size:,}"
        )
        logger.info("⚡ Using sustainable 3-step bulk loading approach")

        start_time = time.time()
        from tqdm import tqdm  # local import to avoid dependency when unused

        for i in tqdm(
            range(0, len(file_changes_data), batch_size),
            total=total_batches,
            desc="Git file changes",
        ):
            batch_start = time.time()
            batch_num = i // batch_size + 1
            batch = file_changes_data[i : i + batch_size]

            # Single-step approach - idempotent creation of nodes and relationships
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
            step_time = time.time() - step_start
            # Keep one concise confirmation per step
            logger.debug(
                "Created %s FileVer nodes and relationships in %.1fs",
                f"{len(batch):,}",
                step_time,
            )

            batch_time = time.time() - batch_start
            elapsed_total = time.time() - start_time
            processed = min(i + batch_size, len(file_changes_data))

            # Enhanced progress reporting
            if processed > 0:
                avg_time_per_batch = elapsed_total / batch_num
                remaining_batches = total_batches - batch_num
                eta_seconds = avg_time_per_batch * remaining_batches
                eta_minutes = eta_seconds / 60

                throughput = processed / elapsed_total
                completion_pct = (processed / len(file_changes_data)) * 100

            logger.debug(
                "Batch %d/%d in %.1fs (%.1f%% done, %.0f rec/s, ETA: %.1fmin)",
                batch_num,
                total_batches,
                batch_time,
                completion_pct,
                throughput,
                eta_minutes,
            )

            # Memory cleanup
            import gc

            gc.collect()

            # Small pause between batches to be gentle on the database
            if batch_num < total_batches:  # Don't pause after the last batch
                time.sleep(0.1)

    finally:
        session.close()


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
                from ..utils.common import create_neo4j_driver

            with create_neo4j_driver(uri, username, password) as driver:
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
    try:
        from utils.common import setup_logging
    except ImportError:
        from ..utils.common import setup_logging

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
            # Import create_neo4j_driver - handle both script and module execution
            try:
                from utils.common import create_neo4j_driver
            except ImportError:
                from ..utils.common import create_neo4j_driver

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
