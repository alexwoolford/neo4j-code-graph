#!/usr/bin/env python
"""
Thin CLI wrapper for git history analysis.
Use the console script entry point (see pyproject.toml) where possible.
"""

from src.analysis.git_analysis import main

if __name__ == "__main__":
    main()
