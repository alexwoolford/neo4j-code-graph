from utils import ensure_port, get_neo4j_config
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_adds_default_port():
    assert ensure_port("bolt://localhost") == "bolt://localhost:7687"


def test_keeps_existing_port():
    assert ensure_port("bolt://localhost:9999") == "bolt://localhost:9999"


def test_handles_auth():
    assert ensure_port("bolt://user:pass@localhost") == ("bolt://user:pass@localhost:7687")


def test_get_neo4j_config_reads_env(monkeypatch):
    # Clear any existing env vars that might interfere
    for var in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"]:
        monkeypatch.delenv(var, raising=False)

    # Mock dotenv to not load from file
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: None)

    # Set test values
    monkeypatch.setenv("NEO4J_URI", "bolt://example")
    monkeypatch.setenv("NEO4J_USERNAME", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "d")

    uri, user, pw, db = get_neo4j_config()

    assert uri == "bolt://example:7687"
    assert user == "u"
    assert pw == "p"
    assert db == "d"
