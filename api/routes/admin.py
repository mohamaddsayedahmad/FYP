"""Admin-only routes — account management operations."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from api.dependencies import get_auth_service, get_course_service
from api.security import require_role
from core.exceptions import NotFoundError
from infrastructure.security.password import validate_password_strength
from services.auth_service import AuthService
from services.course_service import CourseService

router = APIRouter(prefix="/admin", tags=["Admin"])


class RegisterTeacherRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64,
                          description="Login username — must be unique across all accounts")
    name: str = Field(..., min_length=1, max_length=256,
                      description="Teacher's full display name")
    email: EmailStr = Field(..., description="Teacher's contact email address")
    password: str = Field(..., min_length=8,
                          description="Password (minimum 8 characters)")
    course_ids: List[int] = Field(
        default=[],
        description="Course IDs to assign to this teacher immediately on registration",
    )

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class RegisterTeacherResponse(BaseModel):
    account_id: int
    username: str
    name: str
    email: str
    role: str
    courses_assigned: int
    message: str


@router.post(
    "/register-teacher",
    response_model=RegisterTeacherResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new teacher account and assign courses",
    dependencies=[Depends(require_role("admin"))],
)
def register_teacher(
    body: RegisterTeacherRequest,
    auth_svc: AuthService = Depends(get_auth_service),
    course_svc: CourseService = Depends(get_course_service),
) -> RegisterTeacherResponse:
    """
    Create a new teacher account and optionally assign courses in one step.
    Admin role required.

    - `course_ids`: list of course IDs to assign immediately. Pass an empty
      list (or omit) to register the teacher without any course assignments.
    - Returns 404 if any supplied course_id does not exist.
    - Returns 409 if the username is already taken.
    - The password is never logged or echoed in any response.
    """
    # Validate all course IDs before creating the account so we don't
    # leave a dangling account when a bad course ID is supplied.
    for cid in body.course_ids:
        try:
            course_svc.get_course(cid)
        except NotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Course with id={cid} does not exist.",
            )

    if auth_svc.username_exists(body.username.strip()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' is already taken.",
        )

    try:
        account = auth_svc.create_account(
            username=body.username.strip(),
            password=body.password,
            role="teacher",
            name=body.name.strip(),
            email=body.email.lower(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if body.course_ids:
        course_svc.assign_courses_to_teacher(account.id, body.course_ids)

    course_count = len(body.course_ids)
    course_note = (
        f" Assigned to {course_count} course(s)." if course_count else ""
    )

    return RegisterTeacherResponse(
        account_id=account.id,
        username=account.username,
        name=account.name,
        email=account.email,
        role=account.role,
        courses_assigned=course_count,
        message=f"Teacher '{account.name}' registered successfully.{course_note}",
    )
