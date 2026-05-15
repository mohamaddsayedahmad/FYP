# migrate_db.py
"""
Simple schema initializer for the new UID-based design.

You normally don't need this, because database.py already calls init_schema()
on import. This script is only for manual use if you want to force schema creation.
"""

from database import init_schema

if __name__ == "__main__":
    init_schema()
    print("Schema ensured / initialized.")
