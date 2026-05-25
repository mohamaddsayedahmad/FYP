"""
Password hashing and verification using PBKDF2-HMAC-SHA256.

OWASP 2023 recommendation: PBKDF2 with SHA-256, ≥ 600,000 iterations.
We use 600,000 to match the current OWASP guidance while remaining
compatible with the existing 200,000-iteration hashes in the database
(verification still works; the iteration count is stored alongside the hash).

All stored values are URL-safe Base64 to avoid encoding ambiguity.
compare_digest() is used for all comparisons to prevent timing attacks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

_ALGO = "sha256"
_SALT_BYTES = 32          # 256-bit salt
_ITERATIONS_NEW = 600_000
_ITERATIONS_LEGACY = 200_000  # hashes produced by the original database.py


@dataclass(frozen=True)
class HashedPassword:
    hash_b64: str    # Base64-encoded PBKDF2 digest
    salt_b64: str    # Base64-encoded random salt
    iterations: int  # stored to allow future iteration count upgrades


def hash_password(plaintext: str) -> HashedPassword:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(_ALGO, plaintext.encode("utf-8"), salt, _ITERATIONS_NEW)
    return HashedPassword(
        hash_b64=base64.b64encode(digest).decode("utf-8"),
        salt_b64=base64.b64encode(salt).decode("utf-8"),
        iterations=_ITERATIONS_NEW,
    )


def verify_password(plaintext: str, stored: HashedPassword) -> bool:
    try:
        salt = base64.b64decode(stored.salt_b64)
        expected = base64.b64decode(stored.hash_b64)
    except Exception:
        # Try legacy hex encoding used by the original database.py
        try:
            salt = _legacy_decode(stored.salt_b64)
            expected = _legacy_decode(stored.hash_b64)
        except Exception:
            return False

    iterations = stored.iterations if stored.iterations else _ITERATIONS_LEGACY
    actual = hashlib.pbkdf2_hmac(_ALGO, plaintext.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: HashedPassword) -> bool:
    """Return True when the stored hash uses a weaker iteration count."""
    return (stored.iterations or _ITERATIONS_LEGACY) < _ITERATIONS_NEW


def validate_password_strength(password: str) -> None:
    """
    Enforce minimum complexity: at least one letter and one digit.
    Raises ValueError so Pydantic field validators can surface it as HTTP 422.
    """
    if not any(c.isalpha() for c in password):
        raise ValueError("password must contain at least one letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("password must contain at least one digit")


def _legacy_decode(s: str) -> bytes:
    """
    The original database.py stored bytes as either hex or Base64.
    This decoder handles both for backward compatibility.
    """
    import re
    s = s.strip()
    if re.fullmatch(r"[0-9a-fA-F]+", s) and len(s) % 2 == 0 and len(s) >= 16:
        try:
            return bytes.fromhex(s)
        except ValueError:
            pass
    try:
        return base64.b64decode(s, validate=True)
    except Exception:
        pad = (-len(s)) % 4
        return base64.b64decode(s + "=" * pad)
