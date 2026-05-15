"""
Account repository — concrete SQLite implementation of IAccountRepository.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple

from core.entities import Account
from core.interfaces import IAccountRepository
from infrastructure.database.connection import get_connection


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        student_uid=row["student_uid"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )


class SQLiteAccountRepository(IAccountRepository):

    def get_by_username_and_role(self, username: str, role: str) -> Optional[Account]:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, username, role, is_active, student_uid, created_at
                FROM accounts
                WHERE username = ? AND role = ? AND is_active = 1
                LIMIT 1;
                """,
                (username, role),
            )
            row = cur.fetchone()
        return _row_to_account(row) if row else None

    def get_by_id(self, account_id: int) -> Optional[Account]:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, username, role, is_active, student_uid, created_at
                FROM accounts WHERE id = ? LIMIT 1;
                """,
                (account_id,),
            )
            row = cur.fetchone()
        return _row_to_account(row) if row else None

    def save(self, account: Account, password_hash: str, salt: str) -> Account:
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO accounts(username, password_hash, salt, iterations, role,
                                     student_uid, created_at, is_active)
                VALUES (?, ?, ?, 600000, ?, ?, ?, 1)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    salt          = excluded.salt,
                    iterations    = excluded.iterations,
                    role          = excluded.role,
                    student_uid   = excluded.student_uid,
                    is_active     = 1;
                """,
                (account.username, password_hash, salt, account.role,
                 account.student_uid, now),
            )
            cur = conn.execute(
                "SELECT id, username, role, is_active, student_uid, created_at "
                "FROM accounts WHERE username = ? LIMIT 1;",
                (account.username,),
            )
            row = cur.fetchone()
        return _row_to_account(row)

    def get_credentials(self, account_id: int) -> Optional[Tuple[str, str]]:
        """Return (password_hash_b64, salt_b64) for the given account id."""
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT password_hash, salt, iterations FROM accounts WHERE id = ? LIMIT 1;",
                (account_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        iterations = int(row["iterations"]) if row["iterations"] else 200_000
        return row["password_hash"], row["salt"], iterations

    def set_active(self, username: str, role: str, is_active: bool) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE accounts SET is_active = ? WHERE username = ? AND role = ?;",
                (1 if is_active else 0, username, role),
            )

    def get_active_by_role(self, role: str) -> List[Account]:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, username, role, is_active, student_uid, created_at
                FROM accounts
                WHERE role = ? AND is_active = 1
                ORDER BY username ASC;
                """,
                (role,),
            )
            rows = cur.fetchall()
        return [_row_to_account(r) for r in rows]
