from __future__ import annotations

import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


add_src_to_path()

from data import schema_management as sm  # noqa: E402


def test_constraints_include_method_id_and_signature():
    # Inspect the hard-coded cypher statements to ensure presence
    # Pull the constraints list out of the function by reading its compiled code
    # We know the function defines a local 'constraints' list; to avoid runtime db,
    # we re-evaluate by accessing the source attributes.
    # Simpler: re-construct by calling and monkeypatching session.run to capture cypher.

    class DummySession:
        def __init__(self):
            self.cyphers = []

        def run(self, cypher: str):
            self.cyphers.append(cypher)

    session = DummySession()
    sm.create_schema_constraints_and_indexes(session)  # populates cyphers

    text = "\n".join(session.cyphers)
    assert "FOR (m:Method) REQUIRE m.id IS NOT NULL" in text
    assert "FOR (m:Method) REQUIRE m.method_signature IS UNIQUE" in text
    assert "FOR (m:Method) REQUIRE m.method_signature IS NOT NULL" in text
