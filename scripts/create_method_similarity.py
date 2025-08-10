#!/usr/bin/env python
"""
CLI wrapper for method similarity analysis functionality.
"""

import sys
from pathlib import Path

# Add src to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))


# Import and run the main function from the module
def _entry():
    try:
        from analysis.similarity import main
    except ImportError:
        try:
            from src.analysis.similarity import main  # type: ignore
        except ImportError:
            src_path = str((root_dir / "src").resolve())
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            from analysis.similarity import main  # type: ignore
    main()


if __name__ == "__main__":
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("Usage: create_method_similarity.py [--options]\n")
        print("Wrapper around src/analysis/similarity.py")
        sys.exit(0)
    _entry()
