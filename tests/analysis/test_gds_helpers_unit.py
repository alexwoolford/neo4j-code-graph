#!/usr/bin/env python3

import pytest


@pytest.mark.integration
def test_enrich_node_ids_with_method_details(neo4j_driver, mini_method_call_graph):
    try:
        from graphdatascience import GraphDataScience  # type: ignore
    except Exception as e:  # pragma: no cover - environment-specific optional deps
        pytest.skip(f"graphdatascience unavailable (likely tqdm.auto missing): {e}")

    from src.utils.neo4j_utils import get_neo4j_config

    uri, user, pwd, db = get_neo4j_config()
    # Disable Arrow path to avoid optional tqdm.auto import in CI
    gds = GraphDataScience(uri, auth=(user, pwd), database=db, arrow=False)

    from src.analysis.gds_helpers import enrich_node_ids_with_method_details

    # Translate method ids: since we set explicit ids, use them
    node_ids = [1, 2, 3]
    df = enrich_node_ids_with_method_details(gds, node_ids)
    # Expect rows for nodeIds with method_name/class_name/file columns
    assert not df.empty
    assert set(["nodeId", "method_name", "class_name", "file"]).issubset(df.columns)
    gds.close()
