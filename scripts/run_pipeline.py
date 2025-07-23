#!/usr/bin/env python
"""
CLI wrapper for the Python-based pipeline manager.
"""

import sys
from pathlib import Path

# Add src to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))

# Import and run the main function from the pipeline manager
if __name__ == "__main__":
    from pipeline.manager import main

    main()
