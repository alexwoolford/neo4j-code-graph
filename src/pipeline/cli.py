#!/usr/bin/env python3

from __future__ import annotations

import argparse


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the neo4j-code-graph pipeline via Prefect")
    parser.add_argument("--repo-url", dest="repo_url", help="Repository URL or local path")
    parser.add_argument("pos_repo_url", nargs="?", help="Repository URL or local path")
    # Connection and logging flags added by add_common_args are handled at task level; keep simple here
    parser.add_argument("--uri", help="Neo4j URI")
    parser.add_argument("--username", help="Neo4j username")
    parser.add_argument("--password", help="Neo4j password")
    parser.add_argument("--database", help="Neo4j database (overrides .env if set)")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip cleanup stage")
    args = parser.parse_args()
    if not (args.repo_url or args.pos_repo_url):
        parser.error("repo_url is required (use --repo-url or positional)")
    args.repo_url = args.repo_url or args.pos_repo_url
    return args
