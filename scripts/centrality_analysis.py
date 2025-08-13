#!/usr/bin/env python
"""
Thin CLI wrapper for centrality analysis.
Use the console script entry point (see pyproject.toml) where possible.
"""

from src.analysis.centrality import main

if __name__ == "__main__":
    main()
