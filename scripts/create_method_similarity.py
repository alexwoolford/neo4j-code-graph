#!/usr/bin/env python
"""
Thin CLI wrapper for method similarity analysis functionality.
Prefer using the console script or `python -m src.analysis.similarity`.
"""

import sys
from pathlib import Path

try:
    from src.analysis.similarity import main
except ModuleNotFoundError:
    root_dir = Path(__file__).parent.parent / "src"
    sys.path.insert(0, str(root_dir.resolve()))
    from analysis.similarity import main  # type: ignore

if __name__ == "__main__":
    main()
