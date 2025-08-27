#!/usr/bin/env python3

from __future__ import annotations

import argparse


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the neo4j-code-graph pipeline via Prefect")
    parser.add_argument("--repo-url", dest="repo_url", help="Repository URL or local path")
    parser.add_argument("pos_repo_url", nargs="?", help="Repository URL or local path")

    # Use shared connection/logging flags with sensible defaults
    try:
        from src.utils.common import (  # type: ignore[attr-defined]
            add_common_args,
            resolve_neo4j_args,
        )
    except Exception:  # pragma: no cover
        from utils.common import add_common_args, resolve_neo4j_args  # type: ignore

    add_common_args(parser)
    parser.add_argument("--no-cleanup", action="store_true", help="Skip cleanup stage")

    args = parser.parse_args()
    if not (args.repo_url or args.pos_repo_url):
        parser.error("repo_url is required (use --repo-url or positional)")
    args.repo_url = args.repo_url or args.pos_repo_url

    # Resolve connection settings so downstream consumers receive final values
    uri, user, pwd, db = resolve_neo4j_args(args.uri, args.username, args.password, args.database)
    args.uri = uri
    args.username = user
    args.password = pwd
    args.database = db
    return args
