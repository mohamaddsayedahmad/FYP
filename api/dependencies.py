"""
FastAPI dependency injection container.

All services are constructed here once and injected into route handlers via
FastAPI's Depends() mechanism. This is a simple manual DI approach — for a
larger system, consider a DI framework like dependency-injector or punq.

Constructing services here (rather than inside route functions) means:
- Services are created once per process, not per request.
- Swapping an implementation (e.g., for tests) requires only changing this file.
"""

from __future__ import annotations

from functools import lru_cache

from infrastructure.database.account_repo import SQLiteAccountRepository
from infrastructure.database.attendance_repo import SQLiteAttendanceRepository
from infrastructure.database.course_repo import SQLiteCourseRepository
from infrastructure.database.enrollment_repo import SQLiteEnrollmentRepository
from infrastructure.database.student_repo import SQLiteStudentRepository
from infrastructure.email.smtp_gateway import SmtpEmailGateway
from infrastructure.security.encryption import get_encryption_service
from services.attendance_service import AttendanceService
from services.auth_service import AuthService
from services.course_service import CourseService
from services.notification_service import NotificationService
from services.registration_service import RegistrationService


# ---- Notification repo: thin wrapper so the repo layer stays consistent ----

class _SQLiteNotificationRepo:
    """Minimal email notification repository (inline, no separate file needed)."""

    def save(self, notification):
        from datetime import datetime
        from infrastructure.database.connection import get_connection
        with get_connection() as conn:
            now = notification.sent_at.isoformat(timespec="seconds") if notification.sent_at else datetime.now().isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO email_notifications(
                    student_uid, course_id, recipient_email, subject, body,
                    sent_at, status, error_message, attendance_record_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (notification.student_uid, notification.course_id,
                 notification.recipient_email, notification.subject,
                 notification.body, now, notification.status,
                 notification.error_message, notification.attendance_record_id),
            )
        return notification

    def exists(self, student_uid: str, course_id: int, subject: str) -> bool:
        from infrastructure.database.connection import get_connection
        with get_connection() as conn:
            cur = conn.execute(
                "SELECT 1 FROM email_notifications WHERE student_uid=? AND course_id=? AND subject=? LIMIT 1;",
                (student_uid, course_id, subject),
            )
            return cur.fetchone() is not None


@lru_cache(maxsize=1)
def _make_repos():
    return {
        "account": SQLiteAccountRepository(),
        "student": SQLiteStudentRepository(),
        "course": SQLiteCourseRepository(),
        "enrollment": SQLiteEnrollmentRepository(),
        "attendance": SQLiteAttendanceRepository(),
        "notification": _SQLiteNotificationRepo(),
        "email": SmtpEmailGateway(),
        "encryption": get_encryption_service(),
    }


def get_auth_service() -> AuthService:
    r = _make_repos()
    return AuthService(r["account"])


def get_registration_service() -> RegistrationService:
    r = _make_repos()
    return RegistrationService(r["student"], r["encryption"])


def get_attendance_service() -> AttendanceService:
    r = _make_repos()
    return AttendanceService(
        r["attendance"], r["student"], r["course"], r["encryption"]
    )


def get_course_service() -> CourseService:
    r = _make_repos()
    return CourseService(r["course"], r["enrollment"], r["student"])


def get_notification_service() -> NotificationService:
    r = _make_repos()
    return NotificationService(
        r["course"], r["enrollment"], r["attendance"],
        r["notification"], r["email"],
    )
