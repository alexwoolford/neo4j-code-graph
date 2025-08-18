#!/usr/bin/env python3


def test_build_args_adds_flags_and_key_values() -> None:
    from src.pipeline.prefect_flow import _build_args

    base = ["prog"]
    overrides = {"--uri": "bolt://localhost:7687", "--write-back": True, "--top-k": 5}
    args = _build_args(base, overrides)

    # Order: base then flags/kv pairs
    assert args[0] == "prog"
    assert "--uri" in args and "bolt://localhost:7687" in args
    # Boolean True becomes a flag only
    assert "--write-back" in args and "True" not in args
    # Key/value preserved for ints
    i = args.index("--top-k")
    assert args[i + 1] == "5"
