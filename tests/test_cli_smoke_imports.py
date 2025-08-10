#!/usr/bin/env python3
"""
Smoke tests to ensure CLI wrappers and analysis modules import in common contexts.
These tests are lightweight and do not require a running Neo4j instance.
"""

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"


@pytest.mark.unit
def test_wrappers_help_execute_without_import_errors():
    wrappers = [
        SCRIPTS / "code_to_graph.py",
        SCRIPTS / "create_method_similarity.py",
        SCRIPTS / "centrality_analysis.py",
    ]
    for wrapper in wrappers:
        result = subprocess.run(
            [sys.executable, str(wrapper), "--help"], capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0
        # Ensure no import errors leaked to stderr
        assert "Traceback" not in result.stderr
        assert "ImportError" not in result.stderr
        assert "ModuleNotFoundError" not in result.stderr


@pytest.mark.unit
def test_analysis_modules_import_via_runpath_without_main_execution():
    # Ensure module files load and top-level imports resolve without executing main()
    for module_path in [
        SRC / "analysis" / "similarity.py",
        SRC / "analysis" / "centrality.py",
        SRC / "analysis" / "advanced_analysis.py",
    ]:
        # Run with a non-__main__ name to avoid executing main()
        runpy.run_path(str(module_path), run_name="smoke_test")


@pytest.mark.unit
def test_analysis_modules_import_as_package_with_src_on_syspath(monkeypatch):
    # Simulate runtime where 'src' is on sys.path and packages are imported via 'analysis.*'
    src_str = str(SRC.resolve())
    monkeypatch.syspath_prepend(src_str)

    import importlib

    for module_name in ["analysis.similarity", "analysis.centrality"]:
        mod = importlib.import_module(module_name)
        assert mod is not None
