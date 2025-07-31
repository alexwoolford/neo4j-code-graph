#!/usr/bin/env python3
"""
Test CLI script executability.

These tests ensure that all CLI scripts can be imported and executed
without import errors, particularly relative import issues.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestCLIScriptImportability:
    """Test that CLI scripts can be imported without errors."""

    def test_git_history_script_import(self):
        """Test that git_history_to_graph.py can be imported without relative import errors."""
        # This test ensures the git_analysis.py module can be used from CLI
        script_path = Path(__file__).parent.parent / "scripts" / "git_history_to_graph.py"

        # Test that we can import the script without errors
        # We'll use subprocess to simulate actual CLI execution environment
        cmd = [
            sys.executable,
            str(script_path),
            "--help",  # This will test the parse_args() function
        ]

        # Run the command and capture output
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        # Should not fail with ImportError
        if result.returncode != 0:
            # Check if the error is a relative import error
            if "attempted relative import beyond top-level package" in result.stderr:
                pytest.fail(
                    f"CLI script has relative import issue:\n"
                    f"STDERR: {result.stderr}\n"
                    f"STDOUT: {result.stdout}"
                )

        # The script should either succeed (returncode 0) or fail with a different error
        # but NOT with relative import errors
        assert "attempted relative import beyond top-level package" not in result.stderr

    def test_code_to_graph_script_import(self):
        """Test that code_to_graph.py can be imported without relative import errors."""
        script_path = Path(__file__).parent.parent / "scripts" / "code_to_graph.py"

        cmd = [sys.executable, str(script_path), "--help"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        assert "attempted relative import beyond top-level package" not in result.stderr

    def test_similarity_script_import(self):
        """Test that create_method_similarity.py can be imported without relative import errors."""
        script_path = Path(__file__).parent.parent / "scripts" / "create_method_similarity.py"

        cmd = [sys.executable, str(script_path), "--help"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        assert "attempted relative import beyond top-level package" not in result.stderr

    def test_centrality_script_import(self):
        """Test that centrality_analysis.py can be imported without relative import errors."""
        script_path = Path(__file__).parent.parent / "scripts" / "centrality_analysis.py"

        cmd = [sys.executable, str(script_path), "--help"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        assert "attempted relative import beyond top-level package" not in result.stderr

    def test_cleanup_script_import(self):
        """Test that cleanup_graph.py can be imported without relative import errors."""
        script_path = Path(__file__).parent.parent / "scripts" / "cleanup_graph.py"

        cmd = [sys.executable, str(script_path), "--help"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        assert "attempted relative import beyond top-level package" not in result.stderr

    @pytest.mark.parametrize(
        "script_name",
        [
            "git_history_to_graph.py",
            "code_to_graph.py",
            "create_method_similarity.py",
            "centrality_analysis.py",
            "cleanup_graph.py",
            "cve_analysis.py",
            "schema_management.py",
        ],
    )
    def test_all_scripts_importable(self, script_name):
        """Test that all CLI scripts can be imported without relative import errors."""
        script_path = Path(__file__).parent.parent / "scripts" / script_name

        if not script_path.exists():
            pytest.skip(f"Script {script_name} does not exist")

        cmd = [sys.executable, str(script_path), "--help"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        # The key assertion - should never have relative import errors
        assert "attempted relative import beyond top-level package" not in result.stderr, (
            f"Script {script_name} has relative import issues:\n"
            f"STDERR: {result.stderr}\n"
            f"STDOUT: {result.stdout}"
        )


class TestLibraryModuleImportability:
    """Test that library modules can be imported both as modules and from scripts."""

    def test_git_analysis_module_import(self):
        """Test that git_analysis can be imported as a module."""
        # Test module import
        try:
            from src.analysis import git_analysis

            assert hasattr(git_analysis, "parse_args")
            assert hasattr(git_analysis, "main")
        except ImportError as e:
            pytest.fail(f"Failed to import git_analysis as module: {e}")

    def test_code_analysis_module_import(self):
        """Test that code_analysis can be imported as a module."""
        try:
            from src.analysis import code_analysis

            assert hasattr(code_analysis, "main")
        except ImportError as e:
            pytest.fail(f"Failed to import code_analysis as module: {e}")

    def test_similarity_module_import(self):
        """Test that similarity can be imported as a module."""
        try:
            from src.analysis import similarity

            assert hasattr(similarity, "parse_args")
            assert hasattr(similarity, "main")
        except ImportError as e:
            # Skip if it's a dependency issue (e.g., PyArrow flight support)
            if "pyarrow" in str(e) or "flight" in str(e):
                pytest.skip(f"Skipping due to optional dependency issue: {e}")
            else:
                pytest.fail(f"Failed to import similarity as module: {e}")


class TestConditionalImportPatterns:
    """Test that conditional import patterns work correctly."""

    def test_conditional_import_from_script_context(self):
        """Test conditional imports work when called from script context."""
        # Create a temporary script that tests the conditional import pattern
        test_script = """
import sys
import os
from pathlib import Path

# Add src to path like CLI scripts do
root_dir = Path(__file__).parent.parent
src_dir = root_dir / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Test the conditional import pattern
try:
    from utils.common import setup_logging
    print("SUCCESS: Absolute import worked")
except ImportError as e:
    print(f"FAILED: Absolute import failed: {e}")
    try:
        from ..utils.common import setup_logging
        print("SUCCESS: Relative import worked")
    except ImportError as e2:
        print(f"FAILED: Both imports failed: {e2}")
        sys.exit(1)

print("Test completed successfully")
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_script)
            f.flush()

            try:
                result = subprocess.run(
                    [sys.executable, f.name],
                    capture_output=True,
                    text=True,
                    cwd=Path(__file__).parent.parent,
                    timeout=10,
                )

                assert result.returncode == 0, (
                    f"Conditional import test failed:\n"
                    f"STDOUT: {result.stdout}\n"
                    f"STDERR: {result.stderr}"
                )
                assert "SUCCESS: Absolute import worked" in result.stdout

            finally:
                os.unlink(f.name)

    def test_conditional_import_from_module_context(self):
        """Test conditional imports work when called from module context."""
        # This simulates importing from within the package structure
        try:
            # This should work with relative imports since we're in a module
            from src.analysis.git_analysis import parse_args

            # Test that parse_args works (it has conditional imports inside)
            with patch("sys.argv", ["test", "dummy_repo", "--help"]):
                with pytest.raises(SystemExit):  # argparse --help exits
                    parse_args()

        except ImportError as e:
            pytest.fail(f"Module context conditional import failed: {e}")
