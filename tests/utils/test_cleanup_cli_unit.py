#!/usr/bin/env python3


def test_cleanup_cli_parsing_and_noop(monkeypatch):
    import sys

    from src.utils.cleanup import parse_args

    old = sys.argv
    try:
        sys.argv = [
            "prog",
            "--uri",
            "bolt://localhost:7687",
            "--username",
            "neo4j",
            "--password",
            "pwd",
            "--database",
            "neo4j",
            "--dry-run",
        ]
        args = parse_args()
        assert args.dry_run is True
        assert args.complete is False
        assert args.fast is False
    finally:
        sys.argv = old
