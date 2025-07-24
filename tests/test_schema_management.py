#!/usr/bin/env python3
"""
Tests for schema_management.py - Schema setup and validation
"""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_schema_management_imports():
    """Test that schema_management module can be imported."""
    from src.data import schema_management

    # Check key functions exist
    assert hasattr(schema_management, "create_schema_constraints_and_indexes")
    assert hasattr(schema_management, "verify_schema_constraints")
    assert hasattr(schema_management, "verify_schema_indexes")
    assert hasattr(schema_management, "setup_complete_schema")


def test_constraint_creation():
    """Test that constraint creation statements are valid."""
    from src.data import schema_management

    # Mock session
    mock_session = Mock()
    mock_session.run = Mock()

    # Call the function
    schema_management.create_schema_constraints_and_indexes(mock_session)

    # Verify session.run was called (should be called for constraints + indexes)
    assert mock_session.run.call_count > 10  # At least 8 constraints + multiple indexes

    # Check that some expected constraint names are in the calls
    call_args = [call[0][0] for call in mock_session.run.call_args_list]
    constraint_calls = [call for call in call_args if "CONSTRAINT" in call]

    # Should have constraints for all major node types
    assert any("directory_path" in call for call in constraint_calls)
    assert any("file_path" in call for call in constraint_calls)
    assert any("method_name_file_line" in call for call in constraint_calls)
    assert any("commit_sha" in call for call in constraint_calls)


def test_constraint_syntax():
    """Test that constraint syntax uses modern REQUIRE syntax."""
    from src.data import schema_management

    mock_session = Mock()
    mock_session.run = Mock()

    schema_management.create_schema_constraints_and_indexes(mock_session)

    # Check that all constraint calls use REQUIRE syntax
    call_args = [call[0][0] for call in mock_session.run.call_args_list]
    constraint_calls = [call for call in call_args if "CONSTRAINT" in call and "CREATE" in call]

    for call in constraint_calls:
        assert "REQUIRE" in call, f"Constraint should use REQUIRE syntax: {call}"
        assert "IS UNIQUE" in call, f"Constraint should use IS UNIQUE syntax: {call}"


def test_verify_schema_functions():
    """Test schema verification functions."""
    from src.data import schema_management

    # Mock session for constraints verification
    mock_session = Mock()
    mock_result = Mock()
    mock_result.__iter__ = Mock(
        return_value=iter(
            [
                {
                    "name": "test_constraint",
                    "type": "UNIQUENESS",
                    "entityType": "NODE",
                    "labelsOrTypes": ["File"],
                    "properties": ["path"],
                }
            ]
        )
    )
    mock_session.run = Mock(return_value=mock_result)

    # Test constraint verification
    constraints = schema_management.verify_schema_constraints(mock_session)
    assert len(constraints) == 1
    assert constraints[0]["name"] == "test_constraint"

    # Test index verification
    mock_result.__iter__ = Mock(
        return_value=iter(
            [
                {
                    "name": "test_index",
                    "type": "BTREE",
                    "entityType": "NODE",
                    "labelsOrTypes": ["Method"],
                    "properties": ["name"],
                    "state": "ONLINE",
                }
            ]
        )
    )

    indexes = schema_management.verify_schema_indexes(mock_session)
    assert len(indexes) == 1
    assert indexes[0]["name"] == "test_index"


def test_natural_key_coverage():
    """Test that all expected natural keys have constraints."""
    from src.data import schema_management

    mock_session = Mock()
    mock_session.run = Mock()

    schema_management.create_schema_constraints_and_indexes(mock_session)

    call_args = [call[0][0] for call in mock_session.run.call_args_list]
    constraint_calls = [call for call in call_args if "CONSTRAINT" in call and "CREATE" in call]

    # Expected node types and their natural keys
    expected_constraints = [
        ("Directory", "path"),
        ("File", "path"),
        ("Class", "name, file"),
        ("Interface", "name, file"),
        ("Method", "name, file, line"),
        ("Commit", "sha"),
        ("Developer", "email"),
        ("FileVer", "sha, path"),
    ]

    for node_type, key_props in expected_constraints:
        # Check that there's a constraint for this node type
        # Pattern should match (variable:NodeType) format
        pattern = f":{node_type}"
        matching_constraints = [call for call in constraint_calls if pattern in call]
        assert (
            len(matching_constraints) > 0
        ), f"Missing constraint for {node_type} natural key: {key_props}. Found constraints: {constraint_calls}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
