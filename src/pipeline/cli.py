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
    parser.add_argument(
        "--resolve-build-deps",
        action="store_true",
        help="Attempt to resolve dependency versions via Maven/Gradle on the cloned repo",
    )
    parser.add_argument(
        "--branch",
        help="Git branch or tag to ingest (applies to checkout and git history)",
    )

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

    # Propagate toggle via env so the flow can read it at runtime
    import os as _os

    if bool(getattr(args, "resolve_build_deps", False)):
        _os.environ["RESOLVE_BUILD_DEPS"] = "true"

    if getattr(args, "branch", None):
        _os.environ["CODE_GRAPH_BRANCH"] = str(args.branch)

    return args
