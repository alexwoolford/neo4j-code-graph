#!/usr/bin/env python
"""
Thin CLI wrapper for code analysis.
Use the console script entry point (see pyproject.toml) where possible.
"""

from src.analysis.code_analysis import main

if __name__ == "__main__":
    main()
