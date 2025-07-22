#!/usr/bin/env python3
"""
Git history loader for Neo4j using optimized git log commands and bulk processing.
"""

import sys
import tempfile
import shutil
import argparse
import logging
import subprocess
import pandas as pd
from pathlib import Path
import time

from git import Repo
from neo4j import GraphDatabase
from utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Load git history into Neo4j")
    parser.add_argument("repo_url", help="URL of the Git repository")
    parser.add_argument("--branch", default="master", help="Branch to process")
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument("--username", default=NEO4J_USERNAME, help="Neo4j username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Optional log file")
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


def extract_git_history(repo_path, branch, max_commits=None):
    """Extract git history using optimized git log commands."""
    logger.info("🚀 Extracting git history...")

    # Build git log command
    cmd = ["git", "log", "--name-only", "--pretty=format:%H|%an|%ae|%ad|%s", "--date=iso", branch]

    if max_commits:
        cmd.append(f"-{max_commits}")

    start_time = time.time()

    # Execute git log
    logger.info("Running git log command...")
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)

    if result.returncode != 0:
        raise Exception(f"Git log failed: {result.stderr}")

    git_time = time.time() - start_time
    logger.info(f"Git log completed in {git_time:.2f}s")

    # Parse output efficiently
    logger.info("Parsing git log output...")
    parse_start = time.time()

    lines = result.stdout.strip().split("\n")
    commits = []
    file_changes = []

    current_commit = None
    commits_processed = 0

    for line in lines:
        if "|" in line and len(line.split("|")) >= 5:
            # New commit line: sha|author|email|date|message
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
            # File change line
            file_changes.append({"sha": current_commit["sha"], "file_path": line.strip()})

    # Don't forget the last commit
    if current_commit:
        commits.append(current_commit)
        commits_processed += 1

    parse_time = time.time() - parse_start
    total_time = git_time + parse_time

    logger.info(
        "Parsed %d commits and %d file changes in %.2fs",
        commits_processed,
        len(file_changes),
        parse_time,
    )
    logger.info(
        "Total extraction: %.2fs (%.1f commits/sec)", total_time, commits_processed / total_time
    )

    return commits, file_changes


def create_dataframes(commits, file_changes):
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
    commits_df,
    developers_df,
    files_df,
    file_changes_df,
    driver,
    database,
    skip_file_changes=False,
    file_changes_only=False,
):
    """Load data to Neo4j using efficient bulk operations with resilience."""
    logger.info("💾 Loading data to Neo4j using bulk operations...")

    def execute_with_retry(session, query, params, description, max_retries=3):
        """Execute query with retry logic and fresh sessions."""
        for attempt in range(max_retries):
            try:
                result = session.run(query, params)
                return result
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {description}: {e}")
                if attempt == max_retries - 1:
                    raise
                # Get fresh session for retry
                session.close()
                session = driver.session(database=database)
        return None

    if not file_changes_only:
        # Note: Schema constraints and indexes are now managed centrally by schema_management.py
        # They should be created via run_pipeline.sh Step 0 or standalone schema setup

        # Load developers
        with driver.session(database=database) as session:
            logger.info(f"Loading {len(developers_df)} developers...")
            developers_data = developers_df.to_dict("records")
            execute_with_retry(
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
        logger.info(f"Loading {len(commits_df)} commits...")
        commits_data = commits_df.to_dict("records")
        for commit in commits_data:
            # Use native datetime objects so Neo4j stores the value as a
            # DateTime instead of a plain string
            commit["date"] = commit["date"].to_pydatetime()

        commit_batch_size = 5000  # Smaller batches for better reliability
        for i in range(0, len(commits_data), commit_batch_size):
            with driver.session(database=database) as session:
                batch = commits_data[i : i + commit_batch_size]
                execute_with_retry(
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
                    f"commits batch {i//commit_batch_size + 1}",
                )
                logger.info(
                    "Loaded %d/%d commits",
                    min(i + commit_batch_size, len(commits_data)),
                    len(commits_data),
                )

        # Load files
        with driver.session(database=database) as session:
            logger.info(f"Loading {len(files_df)} files...")
            files_data = files_df.to_dict("records")
            execute_with_retry(
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

    # OPTIMIZED: Load file changes with much better performance
    logger.info(f"🚀 Loading {len(file_changes_df)} file changes with optimized bulk operations...")
    file_changes_data = file_changes_df.to_dict("records")

    # Use much larger batches - cloud Neo4j can handle this
    batch_size = 25000  # 2.5x larger for better throughput
    total_batches = (len(file_changes_data) + batch_size - 1) // batch_size

    logger.info(f"📦 Processing in {total_batches} batches of {batch_size:,} records each")
    logger.info(f"⚡ Using optimized 3-step bulk loading (was: 5-step MERGE operations)")
    logger.info(f"🎯 Expected performance improvement: 3-5x faster than previous approach")

    start_time = time.time()
    for i in range(0, len(file_changes_data), batch_size):
        batch_start = time.time()
        batch_num = i // batch_size + 1
        batch = file_changes_data[i : i + batch_size]

        logger.info(f"🔄 Processing batch {batch_num}/{total_batches} ({len(batch):,} records)...")

        with driver.session(database=database) as session:
            # STEP 1: Bulk create FileVer nodes (fastest approach)
            step1_start = time.time()
            execute_with_retry(
                session,
                """
                UNWIND $changes AS change
                CREATE (fv:FileVer {sha: change.sha, path: change.file_path})
                """,
                {"changes": batch},
                f"FileVer creation batch {batch_num}",
            )
            step1_time = time.time() - step1_start
            logger.info(f"  ✅ Created {len(batch):,} FileVer nodes in {step1_time:.1f}s")

            # STEP 2: Bulk create CHANGED relationships (using existing commits)
            step2_start = time.time()
            execute_with_retry(
                session,
                """
                UNWIND $changes AS change
                MATCH (c:Commit {sha: change.sha})
                MATCH (fv:FileVer {sha: change.sha, path: change.file_path})
                MERGE (c)-[:CHANGED]->(fv)
                """,
                {"changes": batch},
                f"CHANGED relationships batch {batch_num}",
            )
            step2_time = time.time() - step2_start
            logger.info(f"  ✅ Created {len(batch):,} CHANGED relationships in {step2_time:.1f}s")

            # STEP 3: Bulk create OF_FILE relationships (using existing files)
            step3_start = time.time()
            execute_with_retry(
                session,
                """
                UNWIND $changes AS change
                MATCH (f:File {path: change.file_path})
                MATCH (fv:FileVer {sha: change.sha, path: change.file_path})
                MERGE (fv)-[:OF_FILE]->(f)
                """,
                {"changes": batch},
                f"OF_FILE relationships batch {batch_num}",
            )
            step3_time = time.time() - step3_start
            logger.info(f"  ✅ Created {len(batch):,} OF_FILE relationships in {step3_time:.1f}s")

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

            logger.info(
                f"📊 Batch {batch_num}/{total_batches} COMPLETED in {batch_time:.1f}s "
                f"({completion_pct:.1f}% done, {throughput:.0f} records/sec, ETA: {eta_minutes:.1f}min)"
            )

        # Memory cleanup
        import gc

        gc.collect()


def export_to_csv(commits_df, developers_df, files_df, file_changes_df, output_dir):
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
    repo_url,
    branch,
    driver,
    database=None,
    csv_export=None,
    max_commits=None,
    skip_file_changes=False,
    file_changes_only=False,
):
    """Load git history using optimized approach."""
    tmpdir = tempfile.mkdtemp()

    try:
        # Clone repository
        logger.info(f"📥 Cloning {repo_url}...")
        start_time = time.time()
        repo = Repo.clone_from(repo_url, tmpdir)
        clone_time = time.time() - start_time
        logger.info(f"Repository cloned in {clone_time:.2f}s")

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

        # Extract git history
        commits, file_changes = extract_git_history(tmpdir, branch, max_commits)

        # Create DataFrames
        commits_df, developers_df, files_df, file_changes_df = create_dataframes(
            commits, file_changes
        )

        # Export or load
        if csv_export:
            export_to_csv(commits_df, developers_df, files_df, file_changes_df, csv_export)
        else:
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
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    args = parse_args()

    # Setup logging
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    # Setup Neo4j connection (unless exporting to CSV)
    driver = None
    if not args.csv_export:
        try:
            driver = GraphDatabase.driver(
                ensure_port(args.uri), auth=(args.username, args.password)
            )
            driver.verify_connectivity()
            logger.info(f"Connected to Neo4j at {ensure_port(args.uri)}")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            sys.exit(1)

    try:
        load_history(
            args.repo_url,
            args.branch,
            driver,
            args.database,
            args.csv_export,
            args.max_commits,
            args.skip_file_changes,
            args.file_changes_only,
        )
    finally:
        if driver:
            driver.close()


if __name__ == "__main__":
    main()
