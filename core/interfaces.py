"""
Repository and gateway interfaces (abstract base classes).

These define the contracts that infrastructure implementations must fulfil.
The application/service layer depends only on these abstractions — never on
concrete SQLite, SMTP, or filesystem implementations.

This is the Dependency Inversion Principle: high-level policy (services) must
not depend on low-level details (SQLite). Both depend on the abstraction here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import List, Optional, Tuple

from core.entities import (
    Account,
    AttendanceRecord,
    Course,
    EmailNotification,
    Enrollment,
    Student,
)


# ---------------------------------------------------------------------------
# Repository interfaces
# ---------------------------------------------------------------------------

class IStudentRepository(ABC):
    @abstractmethod
    def get_all(self) -> List[Student]: ...

    @abstractmethod
    def get_by_uid(self, student_uid: str) -> Optional[Student]: ...

    @abstractmethod
    def save(self, student: Student, face_encoding_blob: Optional[bytes]) -> Student: ...

    @abstractmethod
    def get_face_encoding_blob(self, student_uid: str) -> Optional[bytes]: ...

    @abstractmethod
    def get_enrolled_with_encodings(
        self, course_id: int, teacher_account_id: Optional[int] = None
    ) -> List[Tuple[Student, Optional[bytes]]]: ...


class ICourseRepository(ABC):
    @abstractmethod
    def get_all(self) -> List[Course]: ...

    @abstractmethod
    def get_by_id(self, course_id: int) -> Optional[Course]: ...

    @abstractmethod
    def get_by_code(self, code: str) -> Optional[Course]: ...

    @abstractmethod
    def save(self, course: Course) -> Course: ...

    @abstractmethod
    def get_for_student(self, student_uid: str) -> List[Course]: ...

    @abstractmethod
    def get_for_teacher(self, teacher_account_id: int) -> List[Course]: ...

    @abstractmethod
    def set_teacher_assignments(
        self, teacher_account_id: int, course_ids: List[int]
    ) -> None: ...


class IEnrollmentRepository(ABC):
    @abstractmethod
    def enroll(self, enrollment: Enrollment) -> None: ...

    @abstractmethod
    def is_enrolled(self, student_uid: str, course_id: int) -> bool: ...

    @abstractmethod
    def get_students_for_course(
        self, course_id: int, teacher_account_id: Optional[int] = None
    ) -> List[Student]: ...

    @abstractmethod
    def get_students_for_teacher(
        self, teacher_account_id: int, course_id: Optional[int] = None
    ) -> List[Student]: ...


class IAttendanceRepository(ABC):
    @abstractmethod
    def get_all(
        self,
        course_id: Optional[int] = None,
        teacher_account_id: Optional[int] = None,
    ) -> List[AttendanceRecord]: ...

    @abstractmethod
    def get_open_record(
        self, student_uid: str, course_id: int, on_date: date
    ) -> Optional[AttendanceRecord]: ...

    @abstractmethod
    def get_latest_for_student_course(
        self,
        student_uid: str,
        course_id: int,
        on_date: Optional[date] = None,
    ) -> Optional[AttendanceRecord]: ...

    @abstractmethod
    def has_record_for_date(
        self, student_uid: str, course_id: int, on_date: date
    ) -> bool: ...

    @abstractmethod
    def sign_in(self, student_uid: str, course_id: int) -> AttendanceRecord: ...

    @abstractmethod
    def sign_out(self, record_id: int) -> AttendanceRecord: ...

    @abstractmethod
    def insert_absent(self, student_uid: str, course_id: int, on_date: date) -> AttendanceRecord: ...

    @abstractmethod
    def mark_open_as_absent(self, course_id: int, on_date: date) -> List[AttendanceRecord]: ...

    @abstractmethod
    def get_overview_for_course(
        self,
        course_id: int,
        on_date: Optional[date] = None,
        teacher_account_id: Optional[int] = None,
    ) -> List[dict]: ...

    @abstractmethod
    def delete_for_course_date(self, course_id: int, on_date: date) -> int: ...


class IAccountRepository(ABC):
    @abstractmethod
    def get_by_username_and_role(self, username: str, role: str) -> Optional[Account]: ...

    @abstractmethod
    def get_by_id(self, account_id: int) -> Optional[Account]: ...

    @abstractmethod
    def save(self, account: Account, password_hash: str, salt: str) -> Account: ...

    @abstractmethod
    def get_credentials(self, account_id: int) -> Optional[Tuple[str, str]]: ...

    @abstractmethod
    def set_active(self, username: str, role: str, is_active: bool) -> None: ...

    @abstractmethod
    def username_exists(self, username: str) -> bool: ...

    @abstractmethod
    def get_active_by_role(self, role: str) -> List[Account]: ...


class IEmailNotificationRepository(ABC):
    @abstractmethod
    def save(self, notification: EmailNotification) -> EmailNotification: ...

    @abstractmethod
    def exists(
        self, student_uid: str, course_id: int, subject: str
    ) -> bool: ...


# ---------------------------------------------------------------------------
# Gateway interfaces (external services)
# ---------------------------------------------------------------------------

class IEmailGateway(ABC):
    @abstractmethod
    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
    ) -> Tuple[bool, Optional[str]]:
        """Return (success, error_message)."""
        ...

    @abstractmethod
    def is_configured(self) -> bool: ...


class IEncryptionService(ABC):
    @abstractmethod
    def encrypt(self, plaintext: str) -> bytes: ...

    @abstractmethod
    def decrypt(self, ciphertext: bytes) -> str: ...
