import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils import ensure_port


def test_adds_default_port():
    assert ensure_port("bolt://localhost") == "bolt://localhost:7687"


def test_keeps_existing_port():
    assert ensure_port("bolt://localhost:9999") == "bolt://localhost:9999"


def test_handles_auth():
    assert ensure_port("bolt://user:pass@localhost") == (
        "bolt://user:pass@localhost:7687"
    )
