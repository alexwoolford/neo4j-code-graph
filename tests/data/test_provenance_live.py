"""Live provenance HWM CRUD + full->no-op-incremental e2e smoke (WP4)."""

from __future__ import annotations

import os

import pytest

from src.constants import SCHEMA_VERSION
from src.data.provenance import (
    get_last_successful_ingest,
    normalize_repo_url,
    record_ingest_finish,
    record_ingest_start,
)
from tests.integration.incremental_common import (
    build_base_repo,
    full_ingest,
    incremental_ingest,
    snapshot_graph,
    wipe,
)

pytestmark = pytest.mark.live

_URL = "https://example.com/acme/widgets"
_BRANCH = "main"


def _database() -> str:
    return os.getenv("NEO4J_DATABASE", "neo4j")


def test_provenance_hwm_crud_live(neo4j_driver):
    database = _database()
    with neo4j_driver.session(database=database) as s:
        s.run("MATCH (n) DETACH DELETE n").consume()

        # No ingest yet.
        assert get_last_successful_ingest(s, _URL, _BRANCH) is None

        # A running ingest is NOT a high-water mark.
        iid = record_ingest_start(s, _URL, _BRANCH, "sha1", "full", "1.0.0", SCHEMA_VERSION)
        assert get_last_successful_ingest(s, _URL, _BRANCH) is None

        # After success it becomes the HWM.
        record_ingest_finish(s, iid, "success")
        last = get_last_successful_ingest(s, _URL, _BRANCH)
        assert last is not None
        assert last["head_sha"] == "sha1"
        assert last["schema_version"] == SCHEMA_VERSION

        # A later successful ingest supersedes it.
        iid2 = record_ingest_start(s, _URL, _BRANCH, "sha2", "incremental", "1.0.0", SCHEMA_VERSION)
        record_ingest_finish(s, iid2, "success")
        assert get_last_successful_ingest(s, _URL, _BRANCH)["head_sha"] == "sha2"

        # A failed ingest does NOT advance the HWM.
        iid3 = record_ingest_start(s, _URL, _BRANCH, "sha3", "incremental", "1.0.0", SCHEMA_VERSION)
        record_ingest_finish(s, iid3, "failed")
        assert get_last_successful_ingest(s, _URL, _BRANCH)["head_sha"] == "sha2"

        # Other branches are isolated.
        assert get_last_successful_ingest(s, _URL, "release") is None


def test_full_then_noop_incremental_advances_hwm_live(neo4j_driver, tmp_path):
    """Full ingest -> no-op incremental (empty delta): graph unchanged, HWM recorded."""
    database = _database()
    repo = tmp_path / "repo"
    base = build_base_repo(repo)
    url = normalize_repo_url(str(repo))

    with neo4j_driver.session(database=database) as s:
        wipe(s)

    # Full ingest + provenance.
    full_ingest(neo4j_driver, database, repo)
    with neo4j_driver.session(database=database) as s:
        iid = record_ingest_start(s, url, _BRANCH, base, "full", "1.0.0", SCHEMA_VERSION)
        record_ingest_finish(s, iid, "success")
        snap1 = snapshot_graph(s)

    # No new commits -> empty delta -> incremental is a structural no-op.
    changed, deleted = incremental_ingest(neo4j_driver, database, repo, base)
    assert not changed and not deleted

    with neo4j_driver.session(database=database) as s:
        iid2 = record_ingest_start(s, url, _BRANCH, base, "incremental", "1.0.0", SCHEMA_VERSION)
        record_ingest_finish(s, iid2, "success")
        snap2 = snapshot_graph(s)

        # Graph structure unchanged by the no-op incremental.
        assert snap1 == snap2

        # HWM advanced: a fresh successful (incremental) ingest is now latest.
        last = get_last_successful_ingest(s, url, _BRANCH)
        assert last is not None and last["head_sha"] == base
        n = s.run("MATCH (:Ingest) RETURN count(*) AS c").single()["c"]
        assert n == 2
