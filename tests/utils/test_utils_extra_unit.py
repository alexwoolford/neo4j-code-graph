#!/usr/bin/env python3


def test_ensure_port_auth_and_missing_port():
    from src.utils.neo4j_utils import ensure_port

    assert ensure_port("bolt://localhost") == "bolt://localhost:7687"
    assert ensure_port("neo4j://user:pass@host") == "neo4j://user:pass@host:7687"
    assert ensure_port("neo4j://user@host:9999") == "neo4j://user@host:9999"


def test_get_neo4j_config_env_override(monkeypatch):
    from src.utils.neo4j_utils import get_neo4j_config

    monkeypatch.setenv("NEO4J_URI", "bolt://host:9999")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "db")
    uri, u, p, db = get_neo4j_config()
    assert uri.endswith(":9999") and u == "u" and p == "p" and db == "db"
