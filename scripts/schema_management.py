#!/usr/bin/env python
"""
Thin CLI wrapper for database schema management.
Use the console script entry point (see pyproject.toml) where possible.
"""

from src.data.schema_management import main

if __name__ == "__main__":
    main()
