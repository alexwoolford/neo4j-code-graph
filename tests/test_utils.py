import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils import ensure_port, get_neo4j_config


def test_adds_default_port():
    assert ensure_port("bolt://localhost") == "bolt://localhost:7687"


def test_keeps_existing_port():
    assert ensure_port("bolt://localhost:9999") == "bolt://localhost:9999"


def test_handles_auth():
    assert ensure_port("bolt://user:pass@localhost") == (
        "bolt://user:pass@localhost:7687"
    )


def test_get_neo4j_config_reads_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://example")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "d")

    uri, user, pw, db = get_neo4j_config()

    assert uri == "bolt://example:7687"
    assert user == "u"
    assert pw == "p"
    assert db == "d"
