#!/usr/bin/env python3
import pytest


@pytest.mark.integration
def test_setup_schema_task_runs_with_env_or_container(neo4j_driver) -> None:
    # Import inside test to avoid importing Prefect at collection time unnecessarily
    from src.data.schema_management import setup_complete_schema

    with neo4j_driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n").consume()
        setup_complete_schema(s)
        # basic assertion: constraints exist
        names = {r.get("name") for r in s.run("SHOW CONSTRAINTS").data()}
        assert any("method_signature_unique" in n for n in names)
