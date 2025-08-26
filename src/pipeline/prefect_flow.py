"""
Thin wrapper delegating to modular Prefect flow implementation.
"""

from __future__ import annotations

from src.pipeline.cli import parse_cli_args
from src.pipeline.flows.core import code_graph_flow


def main() -> None:
    args = parse_cli_args()
    code_graph_flow(
        repo_url=args.repo_url,
        uri=args.uri,
        username=args.username,
        password=args.password,
        database=args.database,
        cleanup=not args.no_cleanup,
    )


if __name__ == "__main__":
    main()
