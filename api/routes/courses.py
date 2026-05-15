"""Course and enrollment routes."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import get_course_service
from api.security import require_role
from core.exceptions import NotFoundError
from services.course_service import CourseService

router = APIRouter(prefix="/courses", tags=["Courses"])


class CourseCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=256)


class CourseSummary(BaseModel):
    id: int
    code: str
    name: str


class EnrollRequest(BaseModel):
    student_uid: str = Field(..., min_length=1)
    course_id: int
    teacher_account_id: Optional[int] = None


@router.get(
    "/",
    response_model=List[CourseSummary],
    summary="List all courses",
    dependencies=[Depends(require_role("admin", "teacher", "student"))],
)
def list_courses(svc: CourseService = Depends(get_course_service)) -> List[CourseSummary]:
    courses = svc.get_all_courses()
    return [CourseSummary(id=c.id, code=c.code, name=c.name) for c in courses]


@router.post(
    "/",
    response_model=CourseSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new course",
    dependencies=[Depends(require_role("admin"))],
)
def create_course(
    body: CourseCreate,
    svc: CourseService = Depends(get_course_service),
) -> CourseSummary:
    course = svc.create_course(body.code, body.name)
    return CourseSummary(id=course.id, code=course.code, name=course.name)


@router.get(
    "/{course_id}",
    response_model=CourseSummary,
    summary="Get a course by ID",
    dependencies=[Depends(require_role("admin", "teacher", "student"))],
)
def get_course(
    course_id: int,
    svc: CourseService = Depends(get_course_service),
) -> CourseSummary:
    try:
        course = svc.get_course(course_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return CourseSummary(id=course.id, code=course.code, name=course.name)


@router.post(
    "/enroll",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Enroll a student in a course",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def enroll_student(
    body: EnrollRequest,
    svc: CourseService = Depends(get_course_service),
) -> None:
    try:
        svc.enroll_student(body.student_uid, body.course_id, body.teacher_account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/{course_id}/students",
    summary="List students enrolled in a course",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def course_students(
    course_id: int,
    svc: CourseService = Depends(get_course_service),
) -> list:
    try:
        return svc.get_enrolled_students(course_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
