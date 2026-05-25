"""
Domain entities. Pure Python dataclasses — no framework imports.

The domain layer defines WHAT the system is, not HOW it is stored.
All fields use value types; no ORM or database coupling here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional


@dataclass
class Student:
    student_uid: str
    name: str
    email: str
    image_folder: Optional[str] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.student_uid or not self.student_uid.strip():
            raise ValueError("student_uid must be a non-empty string")
        if not self.name or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if not self.email or "@" not in self.email:
            raise ValueError(f"invalid email address: {self.email!r}")
        self.student_uid = self.student_uid.strip()
        self.name = self.name.strip()
        self.email = self.email.strip().lower()


@dataclass
class Course:
    code: str
    name: str
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.code or not self.code.strip():
            raise ValueError("course code must be a non-empty string")
        if not self.name or not self.name.strip():
            raise ValueError("course name must be a non-empty string")
        self.code = self.code.strip().upper()
        self.name = self.name.strip()


@dataclass
class Enrollment:
    student_uid: str
    course_id: int
    teacher_account_id: Optional[int] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class AttendanceRecord:
    student_uid: str
    course_id: int
    date: date
    status: str                        # 'Present' | 'Absent'
    id: Optional[int] = None
    sign_in_time: Optional[time] = None
    sign_out_time: Optional[time] = None
    duration_minutes: Optional[float] = None
    created_at: Optional[datetime] = None

    VALID_STATUSES = frozenset({"Present", "Absent"})

    def __post_init__(self):
        if self.status not in self.VALID_STATUSES:
            raise ValueError(f"invalid status {self.status!r}; must be one of {self.VALID_STATUSES}")

    @property
    def is_complete(self) -> bool:
        return self.sign_in_time is not None and self.sign_out_time is not None

    @property
    def is_open(self) -> bool:
        return self.sign_in_time is not None and self.sign_out_time is None


@dataclass
class Account:
    username: str
    role: str                          # 'admin' | 'teacher' | 'student'
    is_active: bool = True
    id: Optional[int] = None
    student_uid: Optional[str] = None  # only for role='student'
    name: Optional[str] = None         # display name (teacher/admin profiles)
    email: Optional[str] = None        # contact email (teacher/admin profiles)
    created_at: Optional[datetime] = None

    VALID_ROLES = frozenset({"admin", "teacher", "student"})

    def __post_init__(self):
        if self.role not in self.VALID_ROLES:
            raise ValueError(f"invalid role {self.role!r}; must be one of {self.VALID_ROLES}")
        if self.role == "student" and not self.student_uid:
            raise ValueError("student accounts must have a linked student_uid")


@dataclass
class EmailNotification:
    student_uid: str
    course_id: int
    recipient_email: str
    subject: str
    body: str
    status: str                        # 'sent' | 'failed' | 'logged'
    id: Optional[int] = None
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None
    attendance_record_id: Optional[int] = None


@dataclass
class FaceEncodingRecord:
    """Holds the raw (encrypted) encoding blob alongside its metadata."""
    student_uid: str
    encoding_blob: bytes               # Fernet-encrypted JSON list[float]
    image_folder: Optional[str] = None
