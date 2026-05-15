"""
Course repository — concrete SQLite implementation of ICourseRepository.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import List, Optional

from core.entities import Course
from core.interfaces import ICourseRepository
from infrastructure.database.connection import get_connection


def _row_to_course(row: sqlite3.Row) -> Course:
    return Course(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )


class SQLiteCourseRepository(ICourseRepository):

    def get_all(self) -> List[Course]:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT id, code, name, created_at FROM courses ORDER BY code;"
            )
            rows = cur.fetchall()
        return [_row_to_course(r) for r in rows]

    def get_by_id(self, course_id: int) -> Optional[Course]:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT id, code, name, created_at FROM courses WHERE id = ? LIMIT 1;",
                (course_id,),
            )
            row = cur.fetchone()
        return _row_to_course(row) if row else None

    def get_by_code(self, code: str) -> Optional[Course]:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT id, code, name, created_at FROM courses WHERE code = ? LIMIT 1;",
                (code.strip().upper(),),
            )
            row = cur.fetchone()
        return _row_to_course(row) if row else None

    def save(self, course: Course) -> Course:
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO courses(code, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name;
                """,
                (course.code, course.name, now),
            )
        return self.get_by_code(course.code)

    def get_for_student(self, student_uid: str) -> List[Course]:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.id, c.code, c.name, c.created_at
                FROM enrollments e
                JOIN courses c ON c.id = e.course_id
                WHERE e.student_uid = ?
                ORDER BY c.code;
                """,
                (student_uid,),
            )
            rows = cur.fetchall()
        return [_row_to_course(r) for r in rows]

    def get_for_teacher(self, teacher_account_id: int) -> List[Course]:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.id, c.code, c.name, c.created_at
                FROM teacher_courses tc
                JOIN courses c ON c.id = tc.course_id
                WHERE tc.teacher_account_id = ?
                ORDER BY c.code;
                """,
                (teacher_account_id,),
            )
            rows = cur.fetchall()
        return [_row_to_course(r) for r in rows]

    def set_teacher_assignments(
        self, teacher_account_id: int, course_ids: List[int]
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM teacher_courses WHERE teacher_account_id = ?;",
                (teacher_account_id,),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO teacher_courses(teacher_account_id, course_id, created_at) "
                "VALUES (?, ?, ?);",
                [(teacher_account_id, int(cid), now) for cid in course_ids],
            )
