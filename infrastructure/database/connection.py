"""
SQLite connection management.

Design decisions:
1. WAL (Write-Ahead Logging) journal mode — allows concurrent readers during
   writes, critical for Tkinter UI thread + camera thread accessing the DB
   simultaneously without locking each other out.

2. Context manager pattern — connections are always closed even on exception.
   The caller never holds a raw connection reference; they get a cursor inside
   a managed block.

3. Row factory set to sqlite3.Row on every connection so column access is
   always by name, not by index.

4. Foreign key enforcement is ON by default (SQLite defaults it OFF).

5. DB path is resolved from the ATTENDANCE_DB_PATH env var, falling back to
   the attendance.db file next to the database package.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

_DEFAULT_DB = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "attendance.db")
)


def get_db_path() -> str:
    # Read at call-time so that tests can override ATTENDANCE_DB_PATH via
    # monkeypatch/os.environ after the module has been imported.
    return os.path.normpath(os.getenv("ATTENDANCE_DB_PATH", _DEFAULT_DB))


def _make_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -8000;")  # 8 MB page cache
    return conn


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a connection, automatically committing on success and rolling back
    on any exception. The connection is always closed on exit.

    Usage:
        with get_connection() as conn:
            conn.execute(...)
    """
    conn = _make_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """
    Yield a cursor from an *existing* connection. Used when multiple
    operations must share a single transaction.
    """
    cur = conn.cursor()
    try:
        yield cur
    finally:
        pass  # caller controls commit/rollback via get_connection()
