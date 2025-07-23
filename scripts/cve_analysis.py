#!/usr/bin/env python
"""
CLI wrapper for CVE vulnerability analysis functionality.
"""

import sys
from pathlib import Path

# Add src to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))

# Import and run the main function from the module
if __name__ == "__main__":
    from security.cve_analysis import main

    main()
