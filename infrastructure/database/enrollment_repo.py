"""
Enrollment repository — concrete SQLite implementation of IEnrollmentRepository.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import List, Optional

from core.entities import Enrollment, Student
from core.interfaces import IEnrollmentRepository
from infrastructure.database.connection import get_connection


def _row_to_student(row: sqlite3.Row) -> Student:
    return Student(
        student_uid=row["student_uid"],
        name=row["name"],
        email=row["email"],
        image_folder=row["image_folder"] if "image_folder" in row.keys() else None,
    )


class SQLiteEnrollmentRepository(IEnrollmentRepository):

    def enroll(self, enrollment: Enrollment) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO enrollments(student_uid, course_id, teacher_account_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(student_uid, course_id) DO UPDATE SET
                    teacher_account_id = excluded.teacher_account_id;
                """,
                (enrollment.student_uid, enrollment.course_id,
                 enrollment.teacher_account_id, now),
            )

    def is_enrolled(self, student_uid: str, course_id: int) -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT 1 FROM enrollments WHERE student_uid = ? AND course_id = ? LIMIT 1;",
                (student_uid, course_id),
            )
            return cur.fetchone() is not None

    def get_students_for_course(
        self, course_id: int, teacher_account_id: Optional[int] = None
    ) -> List[Student]:
        sql = """
            SELECT u.student_uid, u.name, u.email, u.image_folder
            FROM enrollments e
            JOIN users u ON u.student_uid = e.student_uid
            WHERE e.course_id = ?
        """
        params: list = [int(course_id)]
        if teacher_account_id is not None:
            sql += " AND e.teacher_account_id = ?"
            params.append(int(teacher_account_id))
        sql += " ORDER BY u.student_uid;"

        with get_connection() as conn:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
        return [_row_to_student(r) for r in rows]

    def get_students_for_teacher(
        self, teacher_account_id: int, course_id: Optional[int] = None
    ) -> List[Student]:
        sql = """
            SELECT DISTINCT u.student_uid, u.name, u.email, u.image_folder
            FROM enrollments e
            JOIN users u ON u.student_uid = e.student_uid
            WHERE e.teacher_account_id = ?
        """
        params: list = [int(teacher_account_id)]
        if course_id is not None:
            sql += " AND e.course_id = ?"
            params.append(int(course_id))
        sql += " ORDER BY u.student_uid;"

        with get_connection() as conn:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
        return [_row_to_student(r) for r in rows]
