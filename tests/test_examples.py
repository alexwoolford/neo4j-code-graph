import re
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from neo4j import GraphDatabase


def extract_tag(path: str, tag: str) -> str:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    start = re.compile(rf"\s*//\s*tag::\s*{re.escape(tag)}\s*\[\]\s*")
    end = re.compile(rf"\s*//\s*end::\s*{re.escape(tag)}\s*\[\]\s*")
    buf, on = [], False
    for line in lines:
        if start.match(line):
            on = True
            continue
        if end.match(line):
            break
        if on:
            buf.append(line)
    return "\n".join(buf).strip()


with open("examples/queries.yml", encoding="utf-8") as f:
    CATALOG = yaml.safe_load(f)


@pytest.fixture(scope="session")
def neo4j_session():
    from src.utils.neo4j_utils import get_neo4j_config

    uri, user, pwd, database = get_neo4j_config()
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        # Retry connect in case DB is still starting
        try:
            driver.verify_connectivity()
        except Exception:
            import time as _t

            for _ in range(30):
                _t.sleep(2)
                try:
                    driver.verify_connectivity()
                    break
                except Exception:
                    continue
        with driver.session(database=database) as session:
            yield session


@pytest.mark.parametrize("ex", CATALOG, ids=[e["id"] for e in CATALOG])
@pytest.mark.live
def test_examples_smoke(ex, neo4j_session):
    cypher = extract_tag(ex["file"], ex["tag"])
    result = list(neo4j_session.run(cypher, ex.get("params", {})))
    assert len(result) >= ex.get("expect", {}).get("min_rows", 0)
