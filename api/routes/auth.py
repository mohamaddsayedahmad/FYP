"""Authentication routes — login, token refresh."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import get_auth_service
from api.security import create_access_token
from core.exceptions import AuthenticationError
from services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(admin|teacher|student)$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
    account_id: int
    student_uid: str | None = None


@router.post("/login", response_model=TokenResponse, summary="Obtain a JWT access token")
def login(
    body: LoginRequest,
    auth_svc: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """
    Authenticate with username + password + role. Returns a JWT Bearer token
    valid for the duration configured in ATTENDANCE_TOKEN_EXPIRE_MINUTES.
    """
    try:
        account = auth_svc.authenticate(body.username, body.password, body.role)
    except AuthenticationError:
        # Deliberately vague error message — don't leak whether username exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username, password, or role",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        username=account.username,
        role=account.role,
        account_id=account.id,
        student_uid=account.student_uid,
    )
    return TokenResponse(
        access_token=token,
        role=account.role,
        username=account.username,
        account_id=account.id,
        student_uid=account.student_uid,
    )
