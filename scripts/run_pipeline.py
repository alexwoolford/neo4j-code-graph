#!/usr/bin/env python
"""
Thin CLI wrapper for the Python-based pipeline manager.
Use the console script entry point (see pyproject.toml) where possible.
"""

from src.pipeline.manager import main

if __name__ == "__main__":
    main()
