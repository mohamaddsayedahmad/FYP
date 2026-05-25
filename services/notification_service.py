"""
Notification service — absence emails with deduplication.

Separating email logic from attendance logic allows:
- Testing attendance finalization without SMTP
- Swapping email provider without changing attendance code
- Logging notifications when SMTP is not configured (dev/test mode)
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, Optional

from core.entities import EmailNotification
from core.interfaces import (
    IAttendanceRepository,
    ICourseRepository,
    IEmailGateway,
    IEmailNotificationRepository,
    IEnrollmentRepository,
)

logger = logging.getLogger(__name__)


class NotificationService:

    def __init__(
        self,
        course_repo: ICourseRepository,
        enrollment_repo: IEnrollmentRepository,
        attendance_repo: IAttendanceRepository,
        notification_repo: IEmailNotificationRepository,
        email_gateway: IEmailGateway,
    ) -> None:
        self._courses = course_repo
        self._enrollments = enrollment_repo
        self._attendance = attendance_repo
        self._notifications = notification_repo
        self._email = email_gateway

    def notify_absent_students(
        self, course_id: int, on_date: Optional[date] = None
    ) -> Dict[str, int]:
        """
        Send absence notifications to enrolled students who have no attendance
        record for the given date.

        If SMTP is not configured, the notification is logged with status
        'logged' so the audit trail exists without sending email.
        """
        target_date = on_date or date.today()
        course = self._courses.get_by_id(course_id)
        course_label = (
            f"{course.code} - {course.name}" if course else f"Course #{course_id}"
        )

        enrolled_students = self._enrollments.get_students_for_course(course_id)
        sent = logged = failed = notified = 0

        for student in enrolled_students:
            if self._attendance.has_record_for_date(
                student.student_uid, course_id, target_date
            ):
                continue

            subject = f"Absence Notification — {course_label} ({target_date})"
            body = self._build_absence_email(student.name, course_label, str(target_date))

            if self._notifications.exists(student.student_uid, course_id, subject):
                continue

            now = datetime.now()
            status, error = self._dispatch(student.email, subject, body)

            notification = EmailNotification(
                student_uid=student.student_uid,
                course_id=course_id,
                recipient_email=student.email,
                subject=subject,
                body=body,
                status=status,
                sent_at=now,
                error_message=error,
            )
            self._notifications.save(notification)
            notified += 1

            if status == "sent":
                sent += 1
            elif status == "failed":
                failed += 1
            else:
                logged += 1

        return {"notified": notified, "sent": sent, "logged": logged, "failed": failed}

    def notify_invalid_attendance(
        self, student_uid: str, student_name: str, student_email: str,
        course_id: int, course_label: str, sign_in_time: str,
        on_date: date,
    ) -> None:
        """
        Notify a student whose sign-in was recorded but no sign-out occurred
        (anti-proxy: incomplete session = absent).
        """
        subject = f"Attendance Invalid — {course_label} ({on_date})"
        body = self._build_invalid_attendance_email(
            student_name, course_label, str(on_date), sign_in_time
        )

        if self._notifications.exists(student_uid, course_id, subject):
            return

        status, error = self._dispatch(student_email, subject, body)
        notification = EmailNotification(
            student_uid=student_uid,
            course_id=course_id,
            recipient_email=student_email,
            subject=subject,
            body=body,
            status=status,
            sent_at=datetime.now(),
            error_message=error,
        )
        self._notifications.save(notification)

    def _dispatch(
        self, to_email: str, subject: str, body: str
    ) -> tuple[str, Optional[str]]:
        if not self._email.is_configured():
            logger.info("SMTP not configured — logging notification to %s", to_email)
            return "logged", None
        ok, err = self._email.send(to_email, subject, body)
        if ok:
            return "sent", None
        logger.warning("Failed to send email to %s: %s", to_email, err)
        return "failed", err

    @staticmethod
    def _build_absence_email(name: str, course_label: str, date_str: str) -> str:
        return (
            f"Dear {name},\n\n"
            f"This is an automated notification from the AI Attendance System.\n\n"
            f"Our records indicate you were absent from:\n"
            f"  Course: {course_label}\n"
            f"  Date:   {date_str}\n\n"
            f"If you believe this is incorrect, please contact your instructor.\n\n"
            f"Regards,\nAI Attendance System"
        )

    @staticmethod
    def _build_invalid_attendance_email(
        name: str, course_label: str, date_str: str, sign_in_time: str
    ) -> str:
        return (
            f"Dear {name},\n\n"
            f"Your attendance record for {course_label} on {date_str} is INVALID.\n\n"
            f"A sign-in was recorded at {sign_in_time}, but no sign-out was recorded "
            f"before the session ended.\n\n"
            f"Attendance policy requires both sign-in and sign-out. "
            f"This session has been marked as Absent.\n\n"
            f"If you believe this is an error, please contact your instructor.\n\n"
            f"Regards,\nAI Attendance System"
        )
