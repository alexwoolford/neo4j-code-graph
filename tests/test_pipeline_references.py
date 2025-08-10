#!/usr/bin/env python3
"""
Fail loudly if pipeline scripts reference non-existent files or modules.
"""

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "script",
    [
        "run_pipeline.sh",
    ],
)
def test_scripts_do_not_reference_deleted_files(script):
    scripts_dir = Path(__file__).parent.parent / "scripts"
    script_path = scripts_dir / script
    assert script_path.exists(), f"Missing script: {script_path}"

    content = script_path.read_text(encoding="utf-8")

    # Disallow legacy references that caused pipeline breaks
    forbidden = [
        "scripts/analyze.py",
        "advanced_analysis.py",
    ]
    for needle in forbidden:
        assert needle not in content, f"Forbidden reference found in {script}: {needle}"


def test_temporal_analysis_module_exists():
    module_path = Path(__file__).parent.parent / "src" / "analysis" / "temporal_analysis.py"
    assert module_path.exists(), "Missing src/analysis/temporal_analysis.py"
