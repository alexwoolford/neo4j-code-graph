#!/usr/bin/env python3
"""
CLI wrapper for code analysis functionality.
"""

import sys
from pathlib import Path

# Add src to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))

# Import and run the main function from the module
if __name__ == "__main__":
    from analysis.code_analysis import main
    main() 