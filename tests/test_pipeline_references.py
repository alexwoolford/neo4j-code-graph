#!/usr/bin/env python3
"""
Fail loudly if pipeline scripts reference non-existent files or modules.
"""

from pathlib import Path


def test_no_legacy_pipeline_scripts_present():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    # Ensure legacy shell pipeline is not present
    assert not (
        scripts_dir / "run_pipeline.sh"
    ).exists(), "Legacy run_pipeline.sh should be removed"


def test_temporal_analysis_module_exists():
    module_path = Path(__file__).parent.parent / "src" / "analysis" / "temporal_analysis.py"
    assert module_path.exists(), "Missing src/analysis/temporal_analysis.py"
