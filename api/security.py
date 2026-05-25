"""
JWT authentication for the FastAPI layer.

Design:
- HS256 signed tokens with configurable secret (ATTENDANCE_JWT_SECRET env var).
- Short-lived access tokens (default 60 minutes). For production, use refresh
  tokens and store revoked JTIs in the DB.
- The token payload carries: sub (username), role, account_id, exp.
- FastAPI dependency `require_role(...)` enforces RBAC on any route.

Security notes:
- Never store sensitive data in the payload — JWTs are base64-encoded, not
  encrypted. Anyone with the token can decode the payload.
- The secret must be at least 32 random bytes. Generate with:
    python -c "import secrets; print(secrets.token_hex(32))"
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    import jwt
    from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
except ImportError:
    raise ImportError(
        "PyJWT is required for the API layer. Install with: pip install 'PyJWT>=2.8'"
    )

_SECRET = os.getenv("ATTENDANCE_JWT_SECRET", "").strip()
if not _SECRET:
    import secrets as _secrets
    _SECRET = _secrets.token_hex(32)
    import warnings
    warnings.warn(
        "ATTENDANCE_JWT_SECRET is not set. A random secret was generated for this "
        "session — all tokens will be invalidated on restart. Set this env var in "
        "production.",
        RuntimeWarning, stacklevel=1,
    )

_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ATTENDANCE_TOKEN_EXPIRE_MINUTES", "60"))

_bearer = HTTPBearer(auto_error=True)


def create_access_token(
    username: str,
    role: str,
    account_id: int,
    student_uid: Optional[str] = None,
) -> str:
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "account_id": account_id,
        "student_uid": student_uid,
        "iat": now,
        "exp": now + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    return decode_token(credentials.credentials)


def require_role(*allowed_roles: str):
    """FastAPI dependency factory — raises 403 if the caller's role is not allowed."""

    def _check(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.get('role')}' is not authorised for this endpoint. "
                       f"Required: {list(allowed_roles)}",
            )
        return user

    return _check
