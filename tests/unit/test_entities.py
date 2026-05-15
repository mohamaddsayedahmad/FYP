"""
Unit tests for domain entities — pure Python, zero I/O.

These tests document the business invariants enforced by the entities
themselves and are the fastest tests in the suite (no DB, no network).
"""

from __future__ import annotations

import pytest

from core.entities import Account, AttendanceRecord, Course, Student
from datetime import date


class TestStudent:

    def test_valid_student_creation(self):
        s = Student(student_uid="S001", name="Alice", email="alice@uni.de")
        assert s.student_uid == "S001"
        assert s.email == "alice@uni.de"

    def test_email_is_lowercased(self):
        s = Student(student_uid="S001", name="Alice", email="ALICE@UNI.DE")
        assert s.email == "alice@uni.de"

    def test_student_uid_is_stripped(self):
        s = Student(student_uid="  S001  ", name="Alice", email="a@b.de")
        assert s.student_uid == "S001"

    def test_empty_uid_raises(self):
        with pytest.raises(ValueError, match="student_uid"):
            Student(student_uid="", name="Alice", email="a@b.de")

    def test_invalid_email_raises(self):
        with pytest.raises(ValueError, match="email"):
            Student(student_uid="S001", name="Alice", email="not-an-email")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            Student(student_uid="S001", name="  ", email="a@b.de")


class TestCourse:

    def test_code_is_uppercased(self):
        c = Course(code="cs101", name="Intro to CS")
        assert c.code == "CS101"

    def test_empty_code_raises(self):
        with pytest.raises(ValueError, match="code"):
            Course(code="", name="Intro")


class TestAttendanceRecord:

    def test_valid_status_present(self):
        r = AttendanceRecord(
            student_uid="S001", course_id=1, date=date.today(), status="Present"
        )
        assert r.status == "Present"

    def test_valid_status_absent(self):
        r = AttendanceRecord(
            student_uid="S001", course_id=1, date=date.today(), status="Absent"
        )
        assert r.status == "Absent"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="invalid status"):
            AttendanceRecord(
                student_uid="S001", course_id=1, date=date.today(), status="Late"
            )

    def test_is_open_when_no_sign_out(self):
        from datetime import time
        r = AttendanceRecord(
            student_uid="S001", course_id=1, date=date.today(),
            status="Present", sign_in_time=time(9, 0),
        )
        assert r.is_open is True
        assert r.is_complete is False

    def test_is_complete_when_both_times_set(self):
        from datetime import time
        r = AttendanceRecord(
            student_uid="S001", course_id=1, date=date.today(), status="Present",
            sign_in_time=time(9, 0), sign_out_time=time(11, 0),
        )
        assert r.is_complete is True
        assert r.is_open is False


class TestAccount:

    def test_invalid_role_raises(self):
        with pytest.raises(ValueError, match="invalid role"):
            Account(username="x", role="superuser")

    def test_student_without_uid_raises(self):
        with pytest.raises(ValueError, match="student_uid"):
            Account(username="s001", role="student", student_uid=None)

    def test_admin_without_uid_is_valid(self):
        a = Account(username="admin", role="admin")
        assert a.role == "admin"
