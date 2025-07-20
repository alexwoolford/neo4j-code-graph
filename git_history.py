import sys
import argparse
import logging
from git import Repo
from neo4j import GraphDatabase
from utils import ensure_port, get_neo4j_config

NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE = get_neo4j_config()

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Load git history into Neo4j")
    parser.add_argument("repo", help="Path to the Git repository")
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j URI")
    parser.add_argument("--username", default=NEO4J_USERNAME, help="Neo4j username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--database", default=NEO4J_DATABASE, help="Neo4j database")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--log-file", help="Optional log file")
    return parser.parse_args()


def load_history(repo_path, driver, database=None):
    repo = Repo(repo_path)
    with driver.session(database=database) as session:
        for commit in repo.iter_commits():
            author = getattr(commit, "author", None)
            email = getattr(author, "email", None)
            name = getattr(author, "name", None)
            session.run(
                "MERGE (d:Developer {email:$email}) SET d.name=$name",
                email=email,
                name=name,
            )
            session.run(
                "MERGE (c:Commit {sha:$sha}) SET c.message=$msg",
                sha=commit.hexsha,
                msg=getattr(commit, "message", ""),
            )
            session.run(
                "MATCH (d:Developer {email:$email}), (c:Commit {sha:$sha}) "
                "MERGE (d)-[:AUTHORED]->(c)",
                email=email,
                sha=commit.hexsha,
            )
            for path in getattr(commit, "files", []):
                session.run(
                    "MERGE (fv:FileVer {path:$path, sha:$sha})",
                    path=path,
                    sha=commit.hexsha,
                )
                session.run(
                    "MATCH (c:Commit {sha:$sha}), (fv:FileVer {path:$path, sha:$sha}) "
                    "MERGE (c)-[:CHANGED]->(fv)",
                    sha=commit.hexsha,
                    path=path,
                )


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
    driver = GraphDatabase.driver(
        ensure_port(args.uri), auth=(args.username, args.password)
    )
    driver.verify_connectivity()
    try:
        load_history(args.repo, driver, args.database)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
