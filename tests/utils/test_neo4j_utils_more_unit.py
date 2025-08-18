#!/usr/bin/env python3

from __future__ import annotations


def test_ensure_port_preserves_path_and_existing_port():
    from src.utils.neo4j_utils import ensure_port

    assert ensure_port("bolt://host:7687/db") == "bolt://host:7687/db"
    assert ensure_port("neo4j://user:pass@host:7687/neo4j") == "neo4j://user:pass@host:7687/neo4j"


def test_get_neo4j_config_falls_back_on_empty_env(monkeypatch):
    from src.utils.neo4j_utils import get_neo4j_config

    # Empty strings should be treated as absent and fall back to defaults
    monkeypatch.setenv("NEO4J_URI", "")
    monkeypatch.setenv("NEO4J_USERNAME", "")
    monkeypatch.setenv("NEO4J_PASSWORD", "")
    monkeypatch.setenv("NEO4J_DATABASE", "")
    uri, user, pwd, db = get_neo4j_config()
    assert uri.startswith("bolt://") and ":7687" in uri
    assert user == "neo4j" and pwd == "neo4j" and db == "neo4j"
