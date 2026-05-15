"""User/student routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from api.dependencies import get_registration_service
from api.security import require_role
from core.exceptions import RegistrationError, ValidationError
from services.registration_service import RegistrationService

router = APIRouter(prefix="/users", tags=["Users"])


class RegisterRequest(BaseModel):
    student_uid: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    email: EmailStr
    image_folder: str = Field(..., min_length=1)


class RegisterResponse(BaseModel):
    student_uid: str
    name: str
    email: str
    images_used: int
    message: str


class UserSummary(BaseModel):
    student_uid: str
    name: str
    email: str


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a student with face images",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def register_student(
    body: RegisterRequest,
    reg_svc: RegistrationService = Depends(get_registration_service),
) -> RegisterResponse:
    """
    Register (or update) a student. Reads all image files from image_folder,
    extracts face encodings, stores the encrypted average encoding, and returns
    the number of images that contributed to the enrollment.

    Requires admin or teacher role.
    """
    try:
        student, images_used = reg_svc.register_from_folder(
            student_uid=body.student_uid,
            name=body.name,
            email=body.email,
            image_folder=body.image_folder,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RegistrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return RegisterResponse(
        student_uid=student.student_uid,
        name=student.name,
        email=student.email,
        images_used=images_used,
        message=f"Student '{student.name}' registered successfully using {images_used} image(s).",
    )


@router.get(
    "/",
    response_model=list[UserSummary],
    summary="List all registered students",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def list_users(
    reg_svc: RegistrationService = Depends(get_registration_service),
) -> list[UserSummary]:
    from api.dependencies import _make_repos
    students = _make_repos()["student"].get_all()
    return [UserSummary(student_uid=s.student_uid, name=s.name, email=s.email) for s in students]
