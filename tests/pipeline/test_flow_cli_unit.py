#!/usr/bin/env python3

import pytest


def test_parse_cli_args_requires_repo_url():
    import sys

    from src.pipeline.prefect_flow import parse_cli_args

    old = sys.argv
    try:
        sys.argv = ["prog"]
        with pytest.raises(SystemExit):
            parse_cli_args()
    finally:
        sys.argv = old


def test_parse_cli_args_positional_vs_flag_priority(tmp_path):
    import sys

    from src.pipeline.prefect_flow import parse_cli_args

    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    # When both are provided, the explicit flag should be used
    old = sys.argv
    try:
        sys.argv = [
            "prog",
            "--repo-url",
            str(repo_a),
            str(repo_b),
            "--no-cleanup",
            "--database",
            "neo4j",
        ]
        args = parse_cli_args()
        assert args.repo_url == str(repo_a)
        assert args.no_cleanup is True
        assert args.database == "neo4j"
    finally:
        sys.argv = old
