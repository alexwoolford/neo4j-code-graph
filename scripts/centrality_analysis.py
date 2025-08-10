#!/usr/bin/env python
"""
CLI wrapper for centrality analysis functionality.
"""

import sys
from pathlib import Path

# Add src to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))


# Import and run the main function from the module
def _entry():
    try:
        from analysis.centrality import main
    except ImportError:
        try:
            from src.analysis.centrality import main  # type: ignore
        except ImportError:
            src_path = str((root_dir / "src").resolve())
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            from analysis.centrality import main  # type: ignore
    main()


if __name__ == "__main__":
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("Usage: centrality_analysis.py [--options]\n")
        print("Wrapper around src/analysis/centrality.py")
        sys.exit(0)
    _entry()
