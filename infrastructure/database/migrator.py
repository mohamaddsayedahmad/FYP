"""
Schema migration runner.

Manages a schema_migrations table that records which migrations have been
applied. Each migration is a numbered SQL file in the migrations/ directory.
Migrations are idempotent: running them twice produces the same result.

Design:
- Migrations run inside a transaction; if one fails, it is rolled back and the
  error is re-raised. The DB is left in the last known-good state.
- ALTER TABLE statements that add columns are wrapped in existence checks
  because SQLite does not support IF NOT EXISTS for ALTER TABLE.
- The runner is called once at application startup before any other DB access.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from infrastructure.database.connection import get_connection

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    filename    TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
"""


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(_CREATE_MIGRATIONS_TABLE)
    conn.commit()
    cur = conn.execute("SELECT version FROM schema_migrations ORDER BY version;")
    return {row[0] for row in cur.fetchall()}


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())


def _safe_execute(conn: sqlite3.Connection, sql: str) -> None:
    """
    Execute a single SQL statement, skipping ALTER TABLE ADD COLUMN when the
    column already exists (handles re-running migrations on existing DBs).
    """
    # Detect: ALTER TABLE <tbl> ADD COLUMN <col> ...
    match = re.match(
        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
        sql.strip(),
        re.IGNORECASE,
    )
    if match:
        table, column = match.group(1), match.group(2)
        if _column_exists(conn, table, column):
            return  # already applied

    conn.execute(sql)


def run_migrations() -> None:
    """
    Discover and apply all pending SQL migrations.
    Called once at application startup.
    """
    if not _MIGRATIONS_DIR.exists():
        return

    migration_files = sorted(
        f for f in _MIGRATIONS_DIR.iterdir()
        if f.suffix == ".sql" and re.match(r"^\d+", f.name)
    )

    with get_connection() as conn:
        applied = _applied_versions(conn)

        for path in migration_files:
            version_match = re.match(r"^(\d+)", path.name)
            if not version_match:
                continue
            version = int(version_match.group(1))

            if version in applied:
                continue

            sql_content = path.read_text(encoding="utf-8")
            # Strip line comments before splitting on ";" so that semicolons
            # inside comments (e.g. "-- note; more text") don't become
            # spurious statements.
            stripped_lines = [
                line for line in sql_content.splitlines()
                if not line.strip().startswith("--")
            ]
            stripped_sql = "\n".join(stripped_lines)
            statements = [
                s.strip() for s in stripped_sql.split(";")
                if s.strip()
            ]

            try:
                for stmt in statements:
                    _safe_execute(conn, stmt)
                conn.execute(
                    "INSERT INTO schema_migrations (version, filename) VALUES (?, ?);",
                    (version, path.name),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise RuntimeError(
                    f"Migration {path.name} failed: {exc}"
                ) from exc
