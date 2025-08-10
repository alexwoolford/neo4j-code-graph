#!/usr/bin/env python
"""
CLI wrapper for code analysis functionality.
"""

import sys
from pathlib import Path

# Add src to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))


# Import and run the main function from the module
def _entry():
    try:
        # Preferred when running this script from repo root
        from analysis.code_analysis import main  # when src is on sys.path
    except ImportError:
        try:
            # Fallback to importing inside src package
            from src.analysis.code_analysis import main  # type: ignore
        except ImportError:
            # As a last resort, adjust sys.path to include src dynamically
            src_path = str((root_dir / "src").resolve())
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            from analysis.code_analysis import main  # type: ignore
    main()


if __name__ == "__main__":
    # Lightweight help to avoid importing heavy modules during --help checks
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("Usage: code_to_graph.py <repo_url> [--options]\n")
        print("This is a thin wrapper around src/analysis/code_analysis.py")
        print("Common options:")
        print("  --parallel-files N   Number of files to process in parallel")
        print("  --batch-size N       Embedding batch size override")
        print("  --force-reprocess    Reprocess even if files exist in DB")
        sys.exit(0)
    _entry()
