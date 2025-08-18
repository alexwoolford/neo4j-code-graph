#!/usr/bin/env python3


def test_add_common_args_defaults(monkeypatch):
    import argparse

    from src.utils.common import add_common_args

    # Control env-driven defaults via monkeypatch to make the test deterministic
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "neo4j")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")

    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args([])

    # Flags are present and defaults are set
    assert hasattr(args, "uri") and args.uri
    assert hasattr(args, "username") and args.username
    assert hasattr(args, "password") and args.password
    assert hasattr(args, "database") and args.database
    assert hasattr(args, "log_level") and args.log_level == "INFO"
    assert hasattr(args, "log_file")
