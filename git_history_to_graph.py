import sys
import tempfile
import shutil
import argparse
import logging

from git import Repo
from neo4j import GraphDatabase

from utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Load Git commit history into Neo4j")
    parser.add_argument("repo_url", help="URL of the Git repository")
    parser.add_argument("--branch", default="main", help="Branch to process")
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j connection URI")
    parser.add_argument(
        "--username", default=NEO4J_USERNAME, help="Neo4j authentication username"
    )
    parser.add_argument(
        "--password", default=NEO4J_PASSWORD, help="Neo4j authentication password"
    )
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument(
        "--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)"
    )
    parser.add_argument("--log-file", help="Write logs to this file as well")
    return parser.parse_args()


def load_history(repo_url, branch, driver, database=None):
    """Load commit history from ``branch`` of ``repo_url`` into Neo4j."""
    tmpdir = tempfile.mkdtemp()
    try:
        logger.info("Cloning %s...", repo_url)
        repo = Repo.clone_from(repo_url, tmpdir)
        if branch:
            repo.git.checkout(branch)

        with driver.session(database=database) as session:
            for commit in repo.iter_commits(branch):
                sha = commit.hexsha
                date = commit.committed_datetime.isoformat()
                msg = commit.message.strip()
                email = commit.author.email

                session.run(
                    "MERGE (c:Commit {sha:$sha}) SET c.date=$date, c.msg=$msg",
                    sha=sha,
                    date=date,
                    msg=msg,
                )
                session.run(
                    "MERGE (d:Developer {email:$email}) " "MERGE (d)-[:AUTHORED]->(c)",
                    email=email,
                    sha=sha,
                )

                for path, stats in commit.stats.files.items():
                    loc = stats.get("lines")
                    session.run("MERGE (f:File {path:$path})", path=path)
                    session.run(
                        "MERGE (fv:FileVer {sha:$sha, path:$path}) SET fv.loc=$loc",
                        sha=sha,
                        path=path,
                        loc=loc,
                    )
                    session.run(
                        "MERGE (c:Commit {sha:$sha}) "
                        "MERGE (fv:FileVer {sha:$sha, path:$path}) "
                        "MERGE (c)-[:CHANGED]->(fv)",
                        sha=sha,
                        path=path,
                    )
                    session.run(
                        "MERGE (fv:FileVer {sha:$sha, path:$path}) "
                        "MERGE (f:File {path:$path}) "
                        "MERGE (fv)-[:OF_FILE]->(f)",
                        sha=sha,
                        path=path,
                    )
    except Exception as e:
        logger.error("Error processing repository: %s", e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    args = parse_args()

    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    try:
        driver = GraphDatabase.driver(
            ensure_port(args.uri), auth=(args.username, args.password)
        )
        driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", ensure_port(args.uri))
    except Exception as e:
        logger.error("Failed to connect to Neo4j: %s", e)
        sys.exit(1)

    try:
        load_history(args.repo_url, args.branch, driver, args.database)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
