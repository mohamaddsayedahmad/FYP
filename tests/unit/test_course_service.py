"""Unit tests for CourseService."""

from __future__ import annotations

import pytest

from core.entities import Course, Enrollment, Student
from core.exceptions import NotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(uid: str, student_repo):
    return student_repo.save(Student(student_uid=uid, name=uid, email=f"{uid}@test.com"), None)


def _make_course(code: str, course_repo):
    return course_repo.save(Course(code=code, name=f"{code} course"))


# ---------------------------------------------------------------------------
# enroll_student
# ---------------------------------------------------------------------------

class TestEnrollStudent:

    def test_raises_when_student_not_found(self, course_service, course_repo):
        course = _make_course("CS101", course_repo)
        with pytest.raises(NotFoundError):
            course_service.enroll_student("GHOST", course.id)

    def test_raises_when_course_not_found(self, course_service, student_repo):
        _make_student("S1", student_repo)
        with pytest.raises(NotFoundError):
            course_service.enroll_student("S1", 9999)

    def test_happy_path(self, course_service, student_repo, course_repo):
        _make_student("S2", student_repo)
        course = _make_course("CS102", course_repo)
        course_service.enroll_student("S2", course.id)
        enrolled = course_service.get_enrolled_students(course.id)
        assert any(s["student_uid"] == "S2" for s in enrolled)

    def test_enroll_without_teacher_id(self, course_service, student_repo, course_repo):
        _make_student("S3", student_repo)
        course = _make_course("CS103", course_repo)
        course_service.enroll_student("S3", course.id)  # teacher_account_id defaults to None
        enrolled = course_service.get_enrolled_students(course.id)
        assert len(enrolled) == 1


# ---------------------------------------------------------------------------
# get_courses_for_student
# ---------------------------------------------------------------------------

class TestGetCoursesForStudent:

    def test_returns_enrolled_courses(self, course_service, student_repo, course_repo):
        _make_student("S4", student_repo)
        course = _make_course("CS104", course_repo)
        course_service.enroll_student("S4", course.id)
        courses = course_service.get_courses_for_student("S4")
        assert any(c.id == course.id for c in courses)

    def test_returns_empty_when_not_enrolled(self, course_service):
        assert course_service.get_courses_for_student("NOBODY") == []


# ---------------------------------------------------------------------------
# assign_courses_to_teacher
# ---------------------------------------------------------------------------

class TestAssignCoursesToTeacher:

    def test_raises_when_course_not_found(self, course_service):
        with pytest.raises(NotFoundError):
            course_service.assign_courses_to_teacher(1, [9999])

    def test_assigns_valid_courses(self, course_service, course_repo, auth_service):
        # Need a real teacher account for the FK in teacher_courses to succeed
        teacher = auth_service.create_account("cs_teacher", "tchr_pw1", "teacher")
        course = _make_course("CS105", course_repo)
        course_service.assign_courses_to_teacher(teacher.id, [course.id])  # must not raise


# ---------------------------------------------------------------------------
# get_enrolled_students
# ---------------------------------------------------------------------------

class TestGetEnrolledStudents:

    def test_returns_dicts_with_expected_keys(self, course_service, student_repo, course_repo):
        _make_student("S5", student_repo)
        course = _make_course("CS106", course_repo)
        course_service.enroll_student("S5", course.id)
        result = course_service.get_enrolled_students(course.id)
        assert isinstance(result, list)
        assert result[0]["student_uid"] == "S5"
        assert "name" in result[0] and "email" in result[0]

    def test_returns_empty_for_empty_course(self, course_service, course_repo):
        course = _make_course("CS107", course_repo)
        result = course_service.get_enrolled_students(course.id)
        assert result == []
