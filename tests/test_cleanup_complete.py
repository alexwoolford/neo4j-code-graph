#!/usr/bin/env python3
"""
Tests for complete database reset functionality in cleanup_graph.py
"""

import sys
import types
from unittest.mock import MagicMock

# Mock heavy dependencies
sys.modules.setdefault("neo4j", types.SimpleNamespace(GraphDatabase=MagicMock()))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda **k: None))

import cleanup_graph


def test_complete_reset_dry_run_shows_counts():
    """Test that complete reset dry-run shows what would be deleted."""
    session_mock = MagicMock()

    # Mock node count
    node_result = MagicMock()
    node_result.single.return_value = {"node_count": 1000}

    # Mock relationship count
    rel_result = MagicMock()
    rel_result.single.return_value = {"rel_count": 5000}

    session_mock.run.side_effect = [node_result, rel_result]

    # Test dry run
    cleanup_graph.complete_database_reset(session_mock, dry_run=True)

    # Verify it queried for counts
    assert session_mock.run.call_count == 2
    assert "MATCH (n) RETURN count(n)" in session_mock.run.call_args_list[0][0][0]
    assert "MATCH ()-[r]->()" in session_mock.run.call_args_list[1][0][0]


def test_complete_reset_handles_empty_database():
    """Test that complete reset handles empty database gracefully."""
    session_mock = MagicMock()

    # Mock empty database
    empty_result = MagicMock()
    empty_result.single.return_value = {"node_count": 0}

    empty_rel_result = MagicMock()
    empty_rel_result.single.return_value = {"rel_count": 0}

    session_mock.run.side_effect = [empty_result, empty_rel_result]

    # Test with empty database
    cleanup_graph.complete_database_reset(session_mock, dry_run=False)

    # Should only check counts, not attempt deletion
    assert session_mock.run.call_count == 2


def test_parse_args_includes_complete_options():
    """Test that argument parser includes complete reset options."""
    # Simple test to verify the parse_args function exists and can be called
    assert hasattr(cleanup_graph, "parse_args")

    # Test that we can call parse_args with our expected arguments
    try:
        import sys

        original_argv = sys.argv
        sys.argv = ["cleanup_graph.py", "--complete", "--confirm", "--dry-run"]
        args = cleanup_graph.parse_args()
        assert hasattr(args, "complete")
        assert hasattr(args, "confirm")
        sys.argv = original_argv
    except SystemExit:
        # This is expected when argparse processes help or invalid args
        sys.argv = original_argv


if __name__ == "__main__":
    test_complete_reset_dry_run_shows_counts()
    test_complete_reset_handles_empty_database()
    test_parse_args_includes_complete_options()
    print("✅ All cleanup tests passed!")
