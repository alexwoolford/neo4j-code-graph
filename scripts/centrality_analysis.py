#!/usr/bin/env python
"""
Thin CLI wrapper for centrality analysis.
Prefer using the console script entry point, but allow direct execution.
"""

import sys
from pathlib import Path

try:
    from src.analysis.centrality import main
except ModuleNotFoundError:
    root_dir = Path(__file__).parent.parent / "src"
    sys.path.insert(0, str(root_dir.resolve()))
    from analysis.centrality import main  # type: ignore

if __name__ == "__main__":
    main()
