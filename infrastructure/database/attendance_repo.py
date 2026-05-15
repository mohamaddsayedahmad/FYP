"""
Attendance repository — concrete SQLite implementation of IAttendanceRepository.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time
from typing import Dict, List, Optional

from core.entities import AttendanceRecord
from core.interfaces import IAttendanceRepository
from infrastructure.database.connection import get_connection


def _row_to_record(row: sqlite3.Row) -> AttendanceRecord:
    def _parse_time(s: Optional[str]) -> Optional[time]:
        if not s:
            return None
        try:
            return time.fromisoformat(s)
        except ValueError:
            return None

    return AttendanceRecord(
        id=row["id"],
        student_uid=row["student_uid"],
        course_id=row["course_id"],
        date=date.fromisoformat(row["date"]),
        sign_in_time=_parse_time(row["sign_in_time"]),
        sign_out_time=_parse_time(row["sign_out_time"]),
        duration_minutes=row["duration"],
        status=row["status"] or "Absent",
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )


class SQLiteAttendanceRepository(IAttendanceRepository):

    def get_all(
        self,
        course_id: Optional[int] = None,
        teacher_account_id: Optional[int] = None,
    ) -> List[AttendanceRecord]:
        sql = """
            SELECT a.id, a.student_uid, a.course_id, a.date, a.sign_in_time,
                   a.sign_out_time, a.duration, a.status, a.created_at
            FROM attendance a
        """
        params = []
        where = []

        if teacher_account_id is not None:
            sql += "\nJOIN enrollments e ON e.student_uid = a.student_uid AND e.course_id = a.course_id"
            where.append("e.teacher_account_id = ?")
            params.append(int(teacher_account_id))

        if course_id is not None:
            where.append("a.course_id = ?")
            params.append(int(course_id))

        if where:
            sql += "\nWHERE " + " AND ".join(where)

        sql += "\nORDER BY a.date DESC, a.sign_in_time DESC;"

        with get_connection() as conn:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
        return [_row_to_record(r) for r in rows]

    def get_open_record(
        self, student_uid: str, course_id: int, on_date: date
    ) -> Optional[AttendanceRecord]:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, student_uid, course_id, date, sign_in_time,
                       sign_out_time, duration, status, created_at
                FROM attendance
                WHERE student_uid = ? AND course_id = ? AND date = ?
                  AND sign_in_time IS NOT NULL AND sign_out_time IS NULL
                ORDER BY id DESC LIMIT 1;
                """,
                (student_uid, course_id, on_date.isoformat()),
            )
            row = cur.fetchone()
        return _row_to_record(row) if row else None

    def get_latest_for_student_course(
        self,
        student_uid: str,
        course_id: int,
        on_date: Optional[date] = None,
    ) -> Optional[AttendanceRecord]:
        if on_date:
            sql = """
                SELECT id, student_uid, course_id, date, sign_in_time,
                       sign_out_time, duration, status, created_at
                FROM attendance
                WHERE student_uid = ? AND course_id = ? AND date = ?
                ORDER BY id DESC LIMIT 1;
            """
            params = (student_uid, course_id, on_date.isoformat())
        else:
            sql = """
                SELECT id, student_uid, course_id, date, sign_in_time,
                       sign_out_time, duration, status, created_at
                FROM attendance
                WHERE student_uid = ? AND course_id = ?
                ORDER BY date DESC, sign_in_time DESC, id DESC LIMIT 1;
            """
            params = (student_uid, course_id)

        with get_connection() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
        return _row_to_record(row) if row else None

    def has_record_for_date(
        self, student_uid: str, course_id: int, on_date: date
    ) -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT 1 FROM attendance WHERE student_uid = ? AND course_id = ? AND date = ? LIMIT 1;",
                (student_uid, course_id, on_date.isoformat()),
            )
            return cur.fetchone() is not None

    def sign_in(self, student_uid: str, course_id: int) -> AttendanceRecord:
        today = date.today()
        existing = self.get_open_record(student_uid, course_id, today)
        if existing:
            return existing  # already signed in, idempotent

        now = datetime.now()
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO attendance(student_uid, course_id, date, sign_in_time,
                                       sign_out_time, duration, status, created_at)
                VALUES (?, ?, ?, ?, NULL, NULL, 'Present', ?)
                RETURNING id, student_uid, course_id, date, sign_in_time,
                          sign_out_time, duration, status, created_at;
                """,
                (student_uid, course_id, today.isoformat(),
                 now.time().isoformat(timespec="seconds"),
                 now.isoformat(timespec="seconds")),
            )
            row = cur.fetchone()
        return _row_to_record(row)

    def sign_out(self, record_id: int) -> AttendanceRecord:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT id, student_uid, course_id, date, sign_in_time, sign_out_time, "
                "duration, status, created_at FROM attendance WHERE id = ? LIMIT 1;",
                (record_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"no attendance record with id={record_id}")

            date_str = row["date"]
            sin_str = row["sign_in_time"]
            try:
                dt_in = datetime.fromisoformat(f"{date_str}T{sin_str}")
            except Exception:
                dt_in = datetime.now()

            dt_out = datetime.now()
            duration = (dt_out - dt_in).total_seconds() / 60.0
            sign_out_str = dt_out.time().isoformat(timespec="seconds")

            cur = conn.execute(
                """
                UPDATE attendance
                SET sign_out_time = ?, duration = ?, status = 'Present'
                WHERE id = ?
                RETURNING id, student_uid, course_id, date, sign_in_time,
                          sign_out_time, duration, status, created_at;
                """,
                (sign_out_str, duration, record_id),
            )
            updated = cur.fetchone()
        return _row_to_record(updated)

    def insert_absent(
        self, student_uid: str, course_id: int, on_date: date
    ) -> AttendanceRecord:
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO attendance(student_uid, course_id, date,
                                       sign_in_time, sign_out_time, duration, status, created_at)
                VALUES (?, ?, ?, NULL, NULL, NULL, 'Absent', ?)
                RETURNING id, student_uid, course_id, date, sign_in_time,
                          sign_out_time, duration, status, created_at;
                """,
                (student_uid, course_id, on_date.isoformat(), now),
            )
            row = cur.fetchone()
        return _row_to_record(row)

    def mark_open_as_absent(
        self, course_id: int, on_date: date
    ) -> List[AttendanceRecord]:
        with get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE attendance
                SET status = 'Absent', duration = NULL
                WHERE course_id = ? AND date = ?
                  AND sign_in_time IS NOT NULL AND sign_out_time IS NULL
                  AND COALESCE(status, '') <> 'Absent'
                RETURNING id, student_uid, course_id, date, sign_in_time,
                          sign_out_time, duration, status, created_at;
                """,
                (course_id, on_date.isoformat()),
            )
            rows = cur.fetchall()
        return [_row_to_record(r) for r in rows]

    def get_overview_for_course(
        self,
        course_id: int,
        on_date: Optional[date] = None,
        teacher_account_id: Optional[int] = None,
    ) -> List[Dict]:
        where = ["e.course_id = ?"]
        params: list = [int(course_id)]

        if teacher_account_id is not None:
            where.append("e.teacher_account_id = ?")
            params.append(int(teacher_account_id))

        where_sql = " AND ".join(where)

        if on_date:
            sql = f"""
            SELECT u.student_uid, u.name, u.email,
                   a.date, a.sign_in_time, a.sign_out_time, a.duration,
                   COALESCE(a.status, 'Absent') AS status
            FROM enrollments e
            JOIN users u ON u.student_uid = e.student_uid
            LEFT JOIN attendance a
              ON a.course_id = e.course_id AND a.student_uid = e.student_uid AND a.date = ?
            WHERE {where_sql}
            ORDER BY u.student_uid;
            """
            params = [on_date.isoformat()] + params
        else:
            sql = f"""
            SELECT u.student_uid, u.name, u.email,
                   a.date, a.sign_in_time, a.sign_out_time, a.duration,
                   COALESCE(a.status, 'Absent') AS status
            FROM enrollments e
            JOIN users u ON u.student_uid = e.student_uid
            LEFT JOIN attendance a ON a.id = (
                SELECT at2.id FROM attendance at2
                WHERE at2.course_id = e.course_id AND at2.student_uid = e.student_uid
                ORDER BY at2.date DESC, at2.sign_in_time DESC LIMIT 1
            )
            WHERE {where_sql}
            ORDER BY u.student_uid;
            """

        with get_connection() as conn:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()

        return [dict(r) for r in rows]

    def delete_for_course_date(self, course_id: int, on_date: date) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM attendance WHERE course_id = ? AND date = ?;",
                (course_id, on_date.isoformat()),
            )
            count = cur.fetchone()[0]
            conn.execute(
                "DELETE FROM attendance WHERE course_id = ? AND date = ?;",
                (course_id, on_date.isoformat()),
            )
        return count
