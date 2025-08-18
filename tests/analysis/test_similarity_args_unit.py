#!/usr/bin/env python3


def test_similarity_parse_args_env_overrides(monkeypatch):
    import sys

    from src.analysis.similarity import parse_args

    monkeypatch.setenv("SIMILARITY_TOP_K", "7")
    monkeypatch.setenv("SIM_CUTOFF", "0.9")

    old = sys.argv
    try:
        sys.argv = [
            "prog",
            "--uri",
            "bolt://localhost:7687",
            "--username",
            "neo4j",
            "--password",
            "pass",
            "--database",
            "neo4j",
        ]
        args = parse_args()
        assert args.top_k == 7
        assert abs(args.cutoff - 0.9) < 1e-6
    finally:
        sys.argv = old
