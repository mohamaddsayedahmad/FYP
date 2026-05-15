"""
Student repository — concrete SQLite implementation of IStudentRepository.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple

from core.entities import Student
from core.interfaces import IStudentRepository
from infrastructure.database.connection import get_connection


def _row_to_student(row: sqlite3.Row) -> Student:
    return Student(
        student_uid=row["student_uid"],
        name=row["name"],
        email=row["email"],
        image_folder=row["image_folder"] if "image_folder" in row.keys() else None,
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )


class SQLiteStudentRepository(IStudentRepository):

    def get_all(self) -> List[Student]:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT student_uid, name, email, image_folder, created_at "
                "FROM users ORDER BY student_uid;"
            )
            rows = cur.fetchall()
        return [_row_to_student(r) for r in rows]

    def get_by_uid(self, student_uid: str) -> Optional[Student]:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT student_uid, name, email, image_folder, created_at "
                "FROM users WHERE student_uid = ? LIMIT 1;",
                (student_uid,),
            )
            row = cur.fetchone()
        return _row_to_student(row) if row else None

    def save(self, student: Student, face_encoding_blob: Optional[bytes]) -> Student:
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users(student_uid, name, email, face_encoding, image_folder, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(student_uid) DO UPDATE SET
                    name          = excluded.name,
                    email         = excluded.email,
                    face_encoding = excluded.face_encoding,
                    image_folder  = excluded.image_folder;
                """,
                (student.student_uid, student.name, student.email,
                 face_encoding_blob, student.image_folder, now),
            )
        return self.get_by_uid(student.student_uid)

    def get_face_encoding_blob(self, student_uid: str) -> Optional[bytes]:
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT face_encoding FROM users WHERE student_uid = ? LIMIT 1;",
                (student_uid,),
            )
            row = cur.fetchone()
        return row["face_encoding"] if row else None

    def get_enrolled_with_encodings(
        self,
        course_id: int,
        teacher_account_id: Optional[int] = None,
    ) -> List[Tuple[Student, Optional[bytes]]]:
        """
        Return (Student, encoding_blob) pairs for students enrolled in a course.
        Used by the camera recognition loop — loads only the relevant students,
        not the entire user table.
        """
        sql = """
            SELECT u.student_uid, u.name, u.email, u.image_folder,
                   u.created_at, u.face_encoding
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

        result = []
        for row in rows:
            student = Student(
                student_uid=row["student_uid"],
                name=row["name"],
                email=row["email"],
                image_folder=row["image_folder"],
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            )
            result.append((student, row["face_encoding"]))
        return result
