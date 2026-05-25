"""Unit tests for AttendanceService."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pytest

from core.entities import Course, Enrollment, Student
from core.exceptions import NotFoundError
from services.attendance_service import AttendanceService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def attendance_service(attendance_repo, student_repo, course_repo, encryption_service):
    return AttendanceService(attendance_repo, student_repo, course_repo, encryption_service)


@pytest.fixture
def course(course_repo):
    return course_repo.save(Course(code="ATT01", name="Attendance Course"))


@pytest.fixture
def student(student_repo):
    return student_repo.save(
        Student(student_uid="ASTU01", name="Att Student", email="att@test.com"), None
    )


@pytest.fixture
def enrolled(student, course, enrollment_repo):
    enrollment_repo.enroll(Enrollment(student_uid=student.student_uid, course_id=course.id))
    return student


# ---------------------------------------------------------------------------
# sign_in
# ---------------------------------------------------------------------------

class TestSignIn:

    def test_raises_when_student_not_found(self, attendance_service, course):
        with pytest.raises(NotFoundError):
            attendance_service.sign_in("GHOST", course.id)

    def test_raises_when_course_not_found(self, attendance_service, student):
        with pytest.raises(NotFoundError):
            attendance_service.sign_in(student.student_uid, 9999)

    def test_creates_present_record(self, attendance_service, enrolled, course):
        record = attendance_service.sign_in(enrolled.student_uid, course.id)
        assert record.status == "Present"
        assert record.student_uid == enrolled.student_uid
        assert record.sign_in_time is not None


# ---------------------------------------------------------------------------
# sign_out
# ---------------------------------------------------------------------------

class TestSignOut:

    def test_returns_none_when_no_open_record(self, attendance_service, enrolled, course):
        result = attendance_service.sign_out(enrolled.student_uid, course.id)
        assert result is None

    def test_closes_open_record(self, attendance_service, enrolled, course):
        attendance_service.sign_in(enrolled.student_uid, course.id)
        closed = attendance_service.sign_out(enrolled.student_uid, course.id)
        assert closed is not None
        assert closed.sign_out_time is not None


# ---------------------------------------------------------------------------
# finalize_session
# ---------------------------------------------------------------------------

class TestFinalizeSession:

    def test_raises_when_course_not_found(self, attendance_service):
        with pytest.raises(NotFoundError):
            attendance_service.finalize_session(9999)

    def test_marks_enrolled_student_absent_when_no_record(self, attendance_service, enrolled, course):
        result = attendance_service.finalize_session(course.id, date.today())
        assert result["newly_absent"] == 1
        assert result["total_affected"] >= 1

    def test_open_sign_in_becomes_absent(self, attendance_service, enrolled, course):
        attendance_service.sign_in(enrolled.student_uid, course.id)
        result = attendance_service.finalize_session(course.id, date.today())
        assert result["open_marked_absent"] == 1

    def test_second_finalize_adds_no_new_absences(self, attendance_service, enrolled, course):
        attendance_service.finalize_session(course.id, date.today())
        result = attendance_service.finalize_session(course.id, date.today())
        assert result["newly_absent"] == 0


# ---------------------------------------------------------------------------
# load_enrolled_face_data
# ---------------------------------------------------------------------------

class TestLoadEnrolledFaceData:

    def test_loads_valid_encrypted_encoding(
        self, attendance_service, student_repo, enrollment_repo, course, encryption_service
    ):
        fake_enc = np.zeros(128, dtype="float32")
        blob = encryption_service.encrypt(json.dumps(fake_enc.tolist()))
        stu = student_repo.save(
            Student(student_uid="FACE01", name="Face Stu", email="face@test.com"), blob
        )
        enrollment_repo.enroll(Enrollment(student_uid=stu.student_uid, course_id=course.id))

        encodings, uids, names = attendance_service.load_enrolled_face_data(course.id)
        assert len(encodings) == 1
        assert uids[0] == "FACE01"
        assert encodings[0].shape == (128,)

    def test_skips_student_with_null_encoding(
        self, attendance_service, student_repo, enrollment_repo, course
    ):
        # Explicitly verify enrollment exists with NULL blob before calling service
        stu = student_repo.save(
            Student(student_uid="NOENC01", name="No Enc", email="noenc@test.com"), None
        )
        enrollment_repo.enroll(Enrollment(student_uid=stu.student_uid, course_id=course.id))
        pairs = student_repo.get_enrolled_with_encodings(course.id)
        assert len(pairs) == 1 and pairs[0][1] is None  # sanity-check blob is None

        encodings, uids, names = attendance_service.load_enrolled_face_data(course.id)
        assert "NOENC01" not in uids  # student was skipped (blob=None branch)

    def test_skips_student_with_corrupted_encoding(
        self, attendance_service, student_repo, enrollment_repo, course
    ):
        # Bad bytes → decrypt raises → except branch covers lines 152-155
        bad_blob = b"this-is-not-a-valid-fernet-token"
        stu = student_repo.save(
            Student(student_uid="BAD01", name="Bad Enc", email="bad@test.com"), bad_blob
        )
        enrollment_repo.enroll(Enrollment(student_uid=stu.student_uid, course_id=course.id))

        encodings, uids, names = attendance_service.load_enrolled_face_data(course.id)
        assert "BAD01" not in uids  # student was skipped (exception branch)


# ---------------------------------------------------------------------------
# sign_out_session_students
# ---------------------------------------------------------------------------

class TestSignOutSessionStudents:

    def test_signs_out_all_uids(self, attendance_service, enrolled, course):
        attendance_service.sign_in(enrolled.student_uid, course.id)
        attendance_service.sign_out_session_students(course.id, {enrolled.student_uid})
        # After session sign-out, no open record remains
        result = attendance_service.sign_out(enrolled.student_uid, course.id)
        assert result is None

    def test_handles_empty_set_silently(self, attendance_service, course):
        attendance_service.sign_out_session_students(course.id, set())  # must not raise

    def test_exception_in_sign_out_is_swallowed(self, attendance_service, enrolled, course):
        from unittest.mock import patch
        attendance_service.sign_in(enrolled.student_uid, course.id)
        with patch.object(attendance_service, "sign_out", side_effect=RuntimeError("db error")):
            attendance_service.sign_out_session_students(course.id, {enrolled.student_uid})
        # Must not raise — except clause at line 206-207 catches and logs


# ---------------------------------------------------------------------------
# get_attendance_statistics
# ---------------------------------------------------------------------------

class TestGetAttendanceStatistics:

    def test_returns_zeros_for_empty_course(self, attendance_service, course):
        stats = attendance_service.get_attendance_statistics(course.id)
        assert stats["total_records"] == 0
        assert stats["present"] == 0
        assert stats["attendance_rate"] == 0.0

    def test_calculates_rate_after_sign_in_out(self, attendance_service, enrolled, course):
        attendance_service.sign_in(enrolled.student_uid, course.id)
        attendance_service.sign_out(enrolled.student_uid, course.id)
        stats = attendance_service.get_attendance_statistics(course.id)
        assert stats["total_records"] == 1
        assert stats["present"] == 1
        assert stats["attendance_rate"] == 100.0

    def test_absent_lowers_rate(self, attendance_service, enrolled, course):
        attendance_service.finalize_session(course.id, date.today())
        stats = attendance_service.get_attendance_statistics(course.id)
        assert stats["absent"] >= 1
        assert stats["attendance_rate"] < 100.0


# ---------------------------------------------------------------------------
# get_course_overview / clear_course_date
# ---------------------------------------------------------------------------

class TestDataAccess:

    def test_get_course_overview_returns_list(self, attendance_service, course):
        result = attendance_service.get_course_overview(course.id)
        assert isinstance(result, list)

    def test_get_attendance_returns_list(self, attendance_service, course):
        records = attendance_service.get_attendance(course_id=course.id)
        assert isinstance(records, list)

    def test_clear_course_date_returns_zero_when_no_records(self, attendance_service, course):
        deleted = attendance_service.clear_course_date(course.id, date.today())
        assert deleted == 0

    def test_clear_course_date_removes_records(self, attendance_service, enrolled, course):
        attendance_service.sign_in(enrolled.student_uid, course.id)
        deleted = attendance_service.clear_course_date(course.id, date.today())
        assert deleted == 1
