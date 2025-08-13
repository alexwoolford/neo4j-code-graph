#!/usr/bin/env python
"""
Thin CLI wrapper for code analysis.
Prefer using the console script entry point, but allow direct execution.
"""

import sys
from pathlib import Path

try:
    from src.analysis.code_analysis import main
except ModuleNotFoundError:
    # Fallback for direct execution without installing the package
    root_dir = Path(__file__).parent.parent / "src"
    sys.path.insert(0, str(root_dir.resolve()))
    from analysis.code_analysis import main  # type: ignore

if __name__ == "__main__":
    main()
