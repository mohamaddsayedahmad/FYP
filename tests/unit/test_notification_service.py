"""Unit tests for NotificationService."""

from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

import pytest

from core.entities import Course, EmailNotification, Enrollment, Student
from core.interfaces import IEmailGateway, IEmailNotificationRepository
from services.notification_service import NotificationService


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeEmailGateway(IEmailGateway):
    def __init__(self, configured: bool = True, succeed: bool = True) -> None:
        self._configured = configured
        self._succeed = succeed
        self.calls: list = []

    def is_configured(self) -> bool:
        return self._configured

    def send(self, to_email: str, subject: str, body: str) -> Tuple[bool, Optional[str]]:
        self.calls.append({"to": to_email, "subject": subject})
        return (True, None) if self._succeed else (False, "test-smtp-error")


class _InMemoryNotificationRepo(IEmailNotificationRepository):
    def __init__(self) -> None:
        self._records: list = []

    def save(self, notification: EmailNotification) -> EmailNotification:
        self._records.append(notification)
        return notification

    def exists(self, student_uid: str, course_id: int, subject: str) -> bool:
        return any(
            n.student_uid == student_uid
            and n.course_id == course_id
            and n.subject == subject
            for n in self._records
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def notif_repo():
    return _InMemoryNotificationRepo()


@pytest.fixture
def email_gw():
    return _FakeEmailGateway(configured=True, succeed=True)


@pytest.fixture
def notification_service(course_repo, enrollment_repo, attendance_repo, notif_repo, email_gw):
    return NotificationService(
        course_repo, enrollment_repo, attendance_repo, notif_repo, email_gw
    )


@pytest.fixture
def course(course_repo):
    return course_repo.save(Course(code="NTF01", name="Notify Course"))


@pytest.fixture
def enrolled_student(student_repo, enrollment_repo, course):
    stu = student_repo.save(
        Student(student_uid="NS001", name="Notify Me", email="notify@test.com"), None
    )
    enrollment_repo.enroll(Enrollment(student_uid=stu.student_uid, course_id=course.id))
    return stu


# ---------------------------------------------------------------------------
# notify_absent_students
# ---------------------------------------------------------------------------

class TestNotifyAbsentStudents:

    def test_empty_course_returns_zeros(self, notification_service, course):
        result = notification_service.notify_absent_students(course.id, date.today())
        assert result == {"notified": 0, "sent": 0, "logged": 0, "failed": 0}

    def test_sends_for_absent_student(self, notification_service, enrolled_student, course, email_gw):
        result = notification_service.notify_absent_students(course.id, date.today())
        assert result["notified"] == 1
        assert result["sent"] == 1
        assert len(email_gw.calls) == 1

    def test_skips_student_with_attendance_record(
        self, notification_service, enrolled_student, course, attendance_repo, email_gw
    ):
        attendance_repo.sign_in(enrolled_student.student_uid, course.id)
        result = notification_service.notify_absent_students(course.id, date.today())
        assert result["notified"] == 0
        assert len(email_gw.calls) == 0

    def test_deduplication_skips_already_notified(
        self, notification_service, enrolled_student, course, email_gw
    ):
        notification_service.notify_absent_students(course.id, date.today())
        result = notification_service.notify_absent_students(course.id, date.today())
        assert result["notified"] == 0
        assert len(email_gw.calls) == 1  # second call sends nothing

    def test_log_only_when_smtp_not_configured(
        self, course_repo, enrollment_repo, attendance_repo, notif_repo, enrolled_student, course
    ):
        gw = _FakeEmailGateway(configured=False)
        svc = NotificationService(
            course_repo, enrollment_repo, attendance_repo, notif_repo, gw
        )
        result = svc.notify_absent_students(course.id, date.today())
        assert result["logged"] == 1
        assert result["sent"] == 0

    def test_failed_email_records_failed_status(
        self, course_repo, enrollment_repo, attendance_repo, enrolled_student, course
    ):
        repo = _InMemoryNotificationRepo()
        gw = _FakeEmailGateway(configured=True, succeed=False)
        svc = NotificationService(course_repo, enrollment_repo, attendance_repo, repo, gw)
        result = svc.notify_absent_students(course.id, date.today())
        assert result["failed"] == 1
        assert result["sent"] == 0


# ---------------------------------------------------------------------------
# notify_invalid_attendance
# ---------------------------------------------------------------------------

class TestNotifyInvalidAttendance:

    def _call(self, svc, stu, course):
        svc.notify_invalid_attendance(
            student_uid=stu.student_uid,
            student_name=stu.name,
            student_email=stu.email,
            course_id=course.id,
            course_label="NTF01 - Notify Course",
            sign_in_time="09:00:00",
            on_date=date.today(),
        )

    def test_sends_notification(self, notification_service, enrolled_student, course, email_gw):
        self._call(notification_service, enrolled_student, course)
        assert len(email_gw.calls) == 1

    def test_deduplication_prevents_resend(
        self, notification_service, enrolled_student, course, email_gw
    ):
        self._call(notification_service, enrolled_student, course)
        self._call(notification_service, enrolled_student, course)  # duplicate
        assert len(email_gw.calls) == 1
