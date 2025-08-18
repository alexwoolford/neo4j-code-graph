#!/usr/bin/env python3

from __future__ import annotations


def test_build_args_boolean_and_values():
    from src.pipeline.prefect_flow import _build_args

    args = _build_args(["prog"], {"--no-knn": True, "--top-k": 3, "--cutoff": 0.7})
    assert args[0] == "prog"
    assert "--no-knn" in args and "True" not in args
    i = args.index("--top-k")
    assert args[i + 1] == "3"
    j = args.index("--cutoff")
    assert args[j + 1] == "0.7"


def test_parse_cli_args_flag_over_positional(tmp_path):
    import sys

    from src.pipeline.prefect_flow import parse_cli_args

    repo_flag = tmp_path / "flag"
    repo_pos = tmp_path / "pos"
    repo_flag.mkdir()
    repo_pos.mkdir()

    old = sys.argv
    try:
        sys.argv = [
            "prog",
            "--repo-url",
            str(repo_flag),
            str(repo_pos),
            "--no-cleanup",
        ]
        args = parse_cli_args()
        assert args.repo_url == str(repo_flag)
        assert args.no_cleanup is True
    finally:
        sys.argv = old
