"""
Pytest configuration and shared fixtures.

Key design decisions:
1. Each test gets its own in-memory SQLite database — tests are fully isolated
   and cannot interfere with each other or with the real attendance.db.

2. The ATTENDANCE_DB_PATH env var is patched per-test using monkeypatch so
   that all infrastructure code picks up the temp DB automatically.

3. The encryption key is deterministic across tests so fixtures that write
   encrypted data can be read by subsequent test steps.

4. Services are constructed fresh per test from the patched repositories —
   no global singletons bleed state between tests.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from cryptography.fernet import Fernet

# ---- Deterministic test encryption key ------------------------------------
TEST_FERNET_KEY = Fernet.generate_key()


@pytest.fixture
def tmp_db_path(tmp_path) -> Path:
    """
    Create a fresh SQLite DB in a temp dir, run migrations, and return the path.
    Sets ATTENDANCE_DB_PATH directly before migrations so connection.py picks
    it up (connection.py reads the env var at call time, not import time).
    """
    db = tmp_path / "test_attendance.db"
    os.environ["ATTENDANCE_DB_PATH"] = str(db)
    os.environ["ATTENDANCE_FERNET_KEY"] = TEST_FERNET_KEY.decode()
    os.environ["ATTENDANCE_JWT_SECRET"] = "test-secret-do-not-use-in-production"
    os.environ["ATTENDANCE_LOGIN_RATE_LIMIT"] = "10000/minute"  # effectively off in tests

    from infrastructure.database.migrator import run_migrations
    run_migrations()
    return db


@pytest.fixture(autouse=True)
def patch_env(monkeypatch, tmp_db_path):
    """
    Ensure every test gets the isolated DB path and resets module singletons.
    Depends on tmp_db_path (so migrations already ran before this fixture body).
    """
    monkeypatch.setenv("ATTENDANCE_DB_PATH", str(tmp_db_path))
    monkeypatch.setenv("ATTENDANCE_FERNET_KEY", TEST_FERNET_KEY.decode())
    monkeypatch.setenv("ATTENDANCE_JWT_SECRET", "test-secret-do-not-use-in-production")
    monkeypatch.setenv("ATTENDANCE_LOGIN_RATE_LIMIT", "10000/minute")

    # Reset singletons so they re-read the patched env vars on next access.
    import infrastructure.security.encryption as enc_mod
    enc_mod._default_service = None

    try:
        import api.dependencies as dep_mod
        dep_mod._make_repos.cache_clear()
    except Exception:
        pass

    # Reset in-memory rate-limit counters so previous tests don't affect limits.
    try:
        from api.limiter import reset_limiter
        reset_limiter()
    except Exception:
        pass


@pytest.fixture
def encryption_service():
    from infrastructure.security.encryption import FernetEncryptionService
    return FernetEncryptionService(key=TEST_FERNET_KEY)


@pytest.fixture
def account_repo():
    from infrastructure.database.account_repo import SQLiteAccountRepository
    return SQLiteAccountRepository()


@pytest.fixture
def student_repo():
    from infrastructure.database.student_repo import SQLiteStudentRepository
    return SQLiteStudentRepository()


@pytest.fixture
def course_repo():
    from infrastructure.database.course_repo import SQLiteCourseRepository
    return SQLiteCourseRepository()


@pytest.fixture
def enrollment_repo():
    from infrastructure.database.enrollment_repo import SQLiteEnrollmentRepository
    return SQLiteEnrollmentRepository()


@pytest.fixture
def attendance_repo():
    from infrastructure.database.attendance_repo import SQLiteAttendanceRepository
    return SQLiteAttendanceRepository()


@pytest.fixture
def auth_service(account_repo):
    from services.auth_service import AuthService
    return AuthService(account_repo)


@pytest.fixture
def course_service(course_repo, enrollment_repo, student_repo):
    from services.course_service import CourseService
    return CourseService(course_repo, enrollment_repo, student_repo)
