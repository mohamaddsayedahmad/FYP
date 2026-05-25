"""
Shared rate-limiter instance for all API routes.

Uses slowapi (wraps the `limits` library) with an in-memory sliding-window
counter keyed by client IP address.

The limit strings are read from environment variables at request time (via
lambdas) so that tests can override them by setting the env var before the
request is made — no import-time baking, no test-specific mocks required.

Production env vars:
  ATTENDANCE_LOGIN_RATE_LIMIT   default "5/minute"
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

LOGIN_RATE_LIMIT: str = "5/minute"


def _login_limit() -> str:
    return os.getenv("ATTENDANCE_LOGIN_RATE_LIMIT", LOGIN_RATE_LIMIT)


def reset_limiter() -> None:
    """Clear all in-memory rate-limit counters. Call this between tests."""
    limiter._storage.reset()
