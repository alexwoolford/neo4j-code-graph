#!/usr/bin/env python3
import os
import sys
from dataclasses import dataclass

from neo4j import GraphDatabase

try:
    # preferred: shared helpers
    from src.utils.neo4j_utils import get_neo4j_config
except Exception:
    get_neo4j_config = None  # type: ignore

from src.utils.cypher_validation import run_validation


@dataclass
class DbConfig:
    uri: str
    username: str
    password: str
    database: str


def get_db_config() -> DbConfig:
    if get_neo4j_config is not None:
        uri, user, pwd, db = get_neo4j_config()
        return DbConfig(uri=uri, username=user, password=pwd, database=db)
    # fallback envs (bolt:// for consistency)
    return DbConfig(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "neo4j"),
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )


# use run_validation from src.utils.cypher_validation


def main() -> int:
    cfg = get_db_config()
    failed: list[tuple[str, str]] = []

    with GraphDatabase.driver(cfg.uri, auth=(cfg.username, cfg.password)) as driver:
        with driver.session(database=cfg.database) as session:
            # Connectivity sanity check
            session.run("RETURN 1").consume()

            results = run_validation(session)

    for name, ok, err in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}")
        if err:
            print(f"  -> {err}")
        if not ok:
            failed.append((name, err or "Unknown error"))

    print(
        f"\nSummary: {len([r for r in results if r[1]])} passed, {len([r for r in results if not r[1]])} failed"
    )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
