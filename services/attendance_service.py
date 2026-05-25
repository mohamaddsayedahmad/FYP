"""
Attendance service.

Contains all attendance business logic:
- Sign-in / sign-out with idempotency guards.
- Course session finalization (anti-proxy policy).
- Camera recognition loop decoupled from the UI thread.
- Confidence-scored matching with rejection threshold.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from core.entities import AttendanceRecord
from core.exceptions import NotFoundError
from core.interfaces import (
    IAttendanceRepository,
    ICourseRepository,
    IEncryptionService,
    IStudentRepository,
)

logger = logging.getLogger(__name__)

# Face matching threshold — Euclidean distance in 128-d embedding space.
# Values below this are considered a match. 0.5 balances FAR vs FRR for
# the dlib HOG face model. Lower = stricter = fewer false positives.
DEFAULT_MATCH_THRESHOLD = 0.50


class AttendanceService:

    def __init__(
        self,
        attendance_repo: IAttendanceRepository,
        student_repo: IStudentRepository,
        course_repo: ICourseRepository,
        encryption: IEncryptionService,
    ) -> None:
        self._attendance = attendance_repo
        self._students = student_repo
        self._courses = course_repo
        self._encryption = encryption

    # ------------------------------------------------------------------
    # Sign-in / sign-out
    # ------------------------------------------------------------------

    def sign_in(self, student_uid: str, course_id: int) -> AttendanceRecord:
        """
        Record a sign-in for today. Idempotent — if an open record exists,
        returns it without creating a duplicate.
        """
        if not self._students.get_by_uid(student_uid):
            raise NotFoundError("Student", student_uid)
        if not self._courses.get_by_id(course_id):
            raise NotFoundError("Course", course_id)

        return self._attendance.sign_in(student_uid, course_id)

    def sign_out(self, student_uid: str, course_id: int) -> Optional[AttendanceRecord]:
        """
        Sign out the latest open attendance record. Returns None if no open
        record exists (idempotent — not an error).
        """
        record = self._attendance.get_open_record(student_uid, course_id, date.today())
        if not record:
            return None
        return self._attendance.sign_out(record.id)

    # ------------------------------------------------------------------
    # Session finalization (anti-proxy policy)
    # ------------------------------------------------------------------

    def finalize_session(
        self, course_id: int, on_date: Optional[date] = None
    ) -> Dict[str, int]:
        """
        Apply anti-proxy policy when a teacher ends the session:

        1. Students who signed in but did NOT sign out are marked Absent
           (incomplete attendance is not valid attendance).
        2. Enrolled students with no record at all are marked Absent.

        Returns count summary dict.
        """
        if not self._courses.get_by_id(course_id):
            raise NotFoundError("Course", course_id)

        target_date = on_date or date.today()

        open_records = self._attendance.mark_open_as_absent(course_id, target_date)
        open_count = len(open_records)

        enrolled = self._students.get_enrolled_with_encodings(course_id)
        absent_inserted = 0
        for student, _ in enrolled:
            if not self._attendance.has_record_for_date(
                student.student_uid, course_id, target_date
            ):
                self._attendance.insert_absent(student.student_uid, course_id, target_date)
                absent_inserted += 1

        return {
            "open_marked_absent": open_count,
            "newly_absent": absent_inserted,
            "total_affected": open_count + absent_inserted,
        }

    # ------------------------------------------------------------------
    # Camera recognition loop support
    # ------------------------------------------------------------------

    def load_enrolled_face_data(
        self,
        course_id: int,
        teacher_account_id: Optional[int] = None,
    ) -> Tuple[List[np.ndarray], List[str], List[str]]:
        """
        Load and decrypt face encodings for students enrolled in a course.
        Returns (encodings, student_uids, names).

        Called once before the camera loop starts.
        """
        pairs = self._students.get_enrolled_with_encodings(course_id, teacher_account_id)
        encodings, uids, names = [], [], []

        for student, blob in pairs:
            if blob is None:
                logger.warning("No encoding for %s (%s) — skipped", student.student_uid, student.name)
                continue
            try:
                decrypted = self._encryption.decrypt(blob)
                enc = np.array(json.loads(decrypted), dtype="float32")
                if enc.shape != (128,):
                    raise ValueError(f"unexpected shape {enc.shape}")
                encodings.append(enc)
                uids.append(student.student_uid)
                names.append(student.name)
            except Exception as exc:
                logger.warning(
                    "Failed to load encoding for %s (%s): %s",
                    student.student_uid, student.name, exc,
                )

        return encodings, uids, names

    def process_recognized_face(
        self,
        face_encoding: np.ndarray,
        known_encodings: List[np.ndarray],
        known_uids: List[str],
        known_names: List[str],
        course_id: int,
        already_signed_in: Set[str],
        threshold: float = DEFAULT_MATCH_THRESHOLD,
    ) -> Tuple[Optional[str], Optional[str], float]:
        """
        Match one detected face against known encodings.

        Returns (student_uid, name, confidence) where confidence is
        1 - min_distance (higher = more confident match).
        Returns (None, "Unknown", 0.0) when no match is found.

        Side effect: calls sign_in for the matched student if they have not
        been signed in yet during this session.
        """
        if not known_encodings:
            return None, "Unknown", 0.0

        import face_recognition
        distances = face_recognition.face_distance(known_encodings, face_encoding)
        best_idx = int(np.argmin(distances))
        best_dist = float(distances[best_idx])
        confidence = max(0.0, 1.0 - best_dist)

        if best_dist > threshold:
            return None, "Unknown", confidence

        uid = known_uids[best_idx]
        name = known_names[best_idx]

        if uid not in already_signed_in:
            try:
                self._attendance.sign_in(uid, course_id)
                already_signed_in.add(uid)
                logger.info("Signed in %s (%s) for course %d", uid, name, course_id)
            except Exception as exc:
                logger.error("Failed to sign in %s: %s", uid, exc)

        return uid, name, confidence

    def sign_out_session_students(
        self, course_id: int, student_uids: Set[str]
    ) -> None:
        """Called at the end of a camera session to sign out everyone signed in."""
        for uid in student_uids:
            try:
                self.sign_out(uid, course_id)
            except Exception as exc:
                logger.error("Failed to sign out %s: %s", uid, exc)

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    def get_attendance(
        self,
        course_id: Optional[int] = None,
        teacher_account_id: Optional[int] = None,
    ) -> List[AttendanceRecord]:
        return self._attendance.get_all(course_id, teacher_account_id)

    def get_course_overview(
        self,
        course_id: int,
        on_date: Optional[date] = None,
        teacher_account_id: Optional[int] = None,
    ) -> List[Dict]:
        return self._attendance.get_overview_for_course(
            course_id, on_date, teacher_account_id
        )

    def clear_course_date(self, course_id: int, on_date: date) -> int:
        return self._attendance.delete_for_course_date(course_id, on_date)

    def get_attendance_statistics(
        self, course_id: int, teacher_account_id: Optional[int] = None
    ) -> Dict:
        """
        Compute basic attendance statistics for a course.
        Returns a dict suitable for dashboard display and analytics.
        """
        records = self._attendance.get_all(course_id, teacher_account_id)
        if not records:
            return {
                "total_records": 0, "present": 0, "absent": 0,
                "attendance_rate": 0.0, "unique_students": 0, "unique_dates": 0,
            }

        present = sum(1 for r in records if r.status == "Present")
        absent = len(records) - present
        unique_students = len({r.student_uid for r in records})
        unique_dates = len({r.date for r in records})
        attendance_rate = present / len(records) if records else 0.0

        return {
            "total_records": len(records),
            "present": present,
            "absent": absent,
            "attendance_rate": round(attendance_rate * 100, 2),
            "unique_students": unique_students,
            "unique_dates": unique_dates,
        }
