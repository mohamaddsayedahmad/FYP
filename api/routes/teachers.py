"""
Teacher self-service routes — scoped to the calling teacher's own data.

RBAC design:
- All endpoints require the teacher role and extract the teacher's account_id
  exclusively from the JWT claim, never from a URL parameter.
- This makes cross-teacher data access structurally impossible: a teacher can
  only ever query their own courses, students, and summary.
- Attempts by any other role receive 403.

Endpoints:
  GET /teachers/me/courses  — courses assigned to the calling teacher
  GET /teachers/me/students — distinct students in the teacher's courses
  GET /teachers/me/summary  — KPI summary (course count, student count,
                              today's attendance, this-week attendance)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import get_attendance_service, get_course_service
from api.security import require_role
from services.attendance_service import AttendanceService
from services.course_service import CourseService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teachers", tags=["Teachers"])


# ---- Response models -------------------------------------------------------

class CourseSummary(BaseModel):
    id: int
    code: str
    name: str


class StudentSummary(BaseModel):
    student_uid: str
    name: str
    email: str


class TeacherKPISummary(BaseModel):
    my_courses: int
    my_students: int
    today_attendance: int
    this_week_attendance: int


# ---- Endpoints -------------------------------------------------------------

@router.get(
    "/me/courses",
    response_model=List[CourseSummary],
    summary="List courses assigned to the calling teacher",
)
def my_courses(
    current_user: dict = Depends(require_role("teacher")),
    course_svc: CourseService = Depends(get_course_service),
) -> List[CourseSummary]:
    """
    Returns only courses where this teacher is the assigned instructor.
    The teacher ID comes from the JWT — callers cannot query another teacher's courses.
    """
    teacher_id = current_user["account_id"]
    courses = course_svc.get_courses_for_teacher(teacher_id)
    logger.info("Teacher %d fetched their %d assigned course(s)", teacher_id, len(courses))
    return [CourseSummary(id=c.id, code=c.code, name=c.name) for c in courses]


@router.get(
    "/me/students",
    response_model=List[StudentSummary],
    summary="List distinct students enrolled in the calling teacher's courses",
)
def my_students(
    current_user: dict = Depends(require_role("teacher")),
    course_svc: CourseService = Depends(get_course_service),
) -> List[StudentSummary]:
    """
    Returns the union of students enrolled in any course assigned to this teacher.
    The teacher ID comes from the JWT — callers cannot query another teacher's students.
    """
    teacher_id = current_user["account_id"]
    students = course_svc.get_all_students_for_teacher(teacher_id)
    logger.info("Teacher %d fetched %d student(s)", teacher_id, len(students))
    return [
        StudentSummary(
            student_uid=s["student_uid"],
            name=s["name"],
            email=s["email"],
        )
        for s in students
    ]


@router.get(
    "/me/summary",
    response_model=TeacherKPISummary,
    summary="KPI summary for the calling teacher",
)
def my_summary(
    current_user: dict = Depends(require_role("teacher")),
    course_svc: CourseService = Depends(get_course_service),
    att_svc: AttendanceService = Depends(get_attendance_service),
) -> TeacherKPISummary:
    """
    Returns four KPIs scoped to the calling teacher:
    - my_courses:          number of courses the teacher is assigned to
    - my_students:         distinct students across all their courses
    - today_attendance:    attendance records taken today in their courses
    - this_week_attendance: attendance records in the last 7 days
    All values are 0 when the teacher has no data — never null or absent.
    """
    teacher_id = current_user["account_id"]

    courses = course_svc.get_courses_for_teacher(teacher_id)
    students = course_svc.get_all_students_for_teacher(teacher_id)

    # All attendance records scoped to this teacher; filter by date in Python
    # (acceptable for per-teacher data volumes; avoids adding a new DB query path)
    all_records = att_svc.get_attendance(teacher_account_id=teacher_id)

    today = date.today()
    week_start = today - timedelta(days=6)

    today_count = sum(1 for r in all_records if r.date == today)
    week_count = sum(1 for r in all_records if week_start <= r.date <= today)

    logger.info(
        "Teacher %d summary: courses=%d students=%d today=%d week=%d",
        teacher_id, len(courses), len(students), today_count, week_count,
    )

    return TeacherKPISummary(
        my_courses=len(courses),
        my_students=len(students),
        today_attendance=today_count,
        this_week_attendance=week_count,
    )
