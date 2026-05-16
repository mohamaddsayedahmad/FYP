"""Course management service."""

from __future__ import annotations

from typing import Dict, List, Optional

from core.entities import Course, Enrollment
from core.exceptions import AlreadyExistsError, NotFoundError
from core.interfaces import ICourseRepository, IEnrollmentRepository, IStudentRepository


class CourseService:

    def __init__(
        self,
        course_repo: ICourseRepository,
        enrollment_repo: IEnrollmentRepository,
        student_repo: IStudentRepository,
    ) -> None:
        self._courses = course_repo
        self._enrollments = enrollment_repo
        self._students = student_repo

    def create_course(self, code: str, name: str) -> Course:
        course = Course(code=code, name=name)
        return self._courses.save(course)

    def get_all_courses(self) -> List[Course]:
        return self._courses.get_all()

    def get_course(self, course_id: int) -> Course:
        course = self._courses.get_by_id(course_id)
        if not course:
            raise NotFoundError("Course", course_id)
        return course

    def enroll_student(
        self,
        student_uid: str,
        course_id: int,
        teacher_account_id: Optional[int] = None,
    ) -> None:
        if not self._students.get_by_uid(student_uid):
            raise NotFoundError("Student", student_uid)
        if not self._courses.get_by_id(course_id):
            raise NotFoundError("Course", course_id)

        enrollment = Enrollment(
            student_uid=student_uid,
            course_id=course_id,
            teacher_account_id=teacher_account_id,
        )
        self._enrollments.enroll(enrollment)

    def get_courses_for_student(self, student_uid: str) -> List[Course]:
        return self._courses.get_for_student(student_uid)

    def get_courses_for_teacher(self, teacher_account_id: int) -> List[Course]:
        return self._courses.get_for_teacher(teacher_account_id)

    def assign_courses_to_teacher(
        self, teacher_account_id: int, course_ids: List[int]
    ) -> None:
        for cid in course_ids:
            if not self._courses.get_by_id(cid):
                raise NotFoundError("Course", cid)
        self._courses.set_teacher_assignments(teacher_account_id, course_ids)

    def get_enrolled_students(
        self, course_id: int, teacher_account_id: Optional[int] = None
    ) -> List[Dict]:
        students = self._enrollments.get_students_for_course(course_id, teacher_account_id)
        return [
            {"student_uid": s.student_uid, "name": s.name, "email": s.email}
            for s in students
        ]

    def get_all_students_for_teacher(self, teacher_account_id: int) -> List[Dict]:
        """Return distinct students enrolled across all courses assigned to a teacher."""
        students = self._enrollments.get_students_for_teacher(teacher_account_id)
        return [
            {"student_uid": s.student_uid, "name": s.name, "email": s.email}
            for s in students
        ]
