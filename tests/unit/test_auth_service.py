"""
Unit tests for AuthService.

These tests run against a real (in-memory) SQLite database — no mocking of
the repository layer. Mocking the DB would test the mock, not the code.

Test coverage:
- Account creation stores a hashed password (never plaintext).
- Authentication succeeds with correct credentials.
- Authentication fails with wrong password (timing-safe comparison).
- Authentication fails for inactive accounts.
- Authentication fails for wrong role.
- Default accounts are created when no accounts exist.
- Password rehash is triggered when iteration count is below current standard.
"""

from __future__ import annotations

import pytest

from core.exceptions import AuthenticationError
from services.auth_service import AuthService


class TestAccountCreation:

    def test_create_account_returns_account_entity(self, auth_service):
        account = auth_service.create_account("testuser", "securepass", "teacher")
        assert account.username == "testuser"
        assert account.role == "teacher"
        assert account.id is not None
        assert account.is_active is True

    def test_password_is_never_stored_in_plaintext(self, account_repo, auth_service):
        auth_service.create_account("alice", "my-secret", "admin")
        account = account_repo.get_by_username_and_role("alice", "admin")
        creds = account_repo.get_credentials(account.id)
        hash_b64, salt_b64, _ = creds
        assert "my-secret" not in hash_b64
        assert "my-secret" not in salt_b64

    def test_student_account_links_student_uid(self, auth_service, student_repo):
        # A student account FK-references users.student_uid, so the user must exist first.
        from core.entities import Student
        student_repo.save(Student(student_uid="S12345", name="Test", email="t@t.de"), None)
        account = auth_service.create_account("S12345", "pass", "student", student_uid="S12345")
        assert account.student_uid == "S12345"

    def test_create_account_is_idempotent_on_conflict(self, auth_service):
        auth_service.create_account("bob", "pass1", "teacher")
        auth_service.create_account("bob", "pass2", "teacher")  # update
        account = auth_service.authenticate("bob", "pass2", "teacher")
        assert account.username == "bob"


class TestAuthentication:

    def test_correct_credentials_return_account(self, auth_service):
        auth_service.create_account("carol", "correct-pass", "admin")
        account = auth_service.authenticate("carol", "correct-pass", "admin")
        assert account.username == "carol"
        assert account.role == "admin"

    def test_wrong_password_raises(self, auth_service):
        auth_service.create_account("dave", "correct", "teacher")
        with pytest.raises(AuthenticationError):
            auth_service.authenticate("dave", "wrong", "teacher")

    def test_wrong_role_raises(self, auth_service):
        auth_service.create_account("eve", "pass", "teacher")
        with pytest.raises(AuthenticationError):
            auth_service.authenticate("eve", "pass", "admin")

    def test_nonexistent_user_raises(self, auth_service):
        with pytest.raises(AuthenticationError):
            auth_service.authenticate("nobody", "pass", "admin")

    def test_inactive_account_raises(self, auth_service, account_repo):
        auth_service.create_account("frank", "pass", "teacher")
        account_repo.set_active("frank", "teacher", False)
        with pytest.raises(AuthenticationError):
            auth_service.authenticate("frank", "pass", "teacher")


class TestDefaultAccounts:

    def test_ensure_defaults_creates_admin_when_none_exist(self, auth_service):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            auth_service.ensure_default_accounts()
        account = auth_service.authenticate("admin", "admin123", "admin")
        assert account.username == "admin"
        assert account.role == "admin"

    def test_ensure_defaults_is_idempotent(self, auth_service):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            auth_service.ensure_default_accounts()
            auth_service.ensure_default_accounts()  # second call must not fail
        account = auth_service.authenticate("admin", "admin123", "admin")
        assert account is not None

    def test_ensure_defaults_does_not_overwrite_existing(self, auth_service):
        auth_service.create_account("admin", "my-strong-password", "admin")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            auth_service.ensure_default_accounts()
        # Original strong password must still work
        account = auth_service.authenticate("admin", "my-strong-password", "admin")
        assert account is not None


class TestPasswordRehash:

    def test_authenticate_rehashes_legacy_iteration_count(self, auth_service, account_repo):
        import base64
        import hashlib
        import secrets as _secrets

        auth_service.create_account("rehash_user", "placeholder", "teacher")
        account = account_repo.get_by_username_and_role("rehash_user", "teacher")

        # Overwrite with a proper 200k-iteration hash so verify_password succeeds
        password = "rehash_pw1"
        salt = _secrets.token_bytes(32)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        hash_b64 = base64.b64encode(digest).decode()
        salt_b64 = base64.b64encode(salt).decode()

        from infrastructure.database.connection import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE accounts SET password_hash=?, salt=?, iterations=200000 "
                "WHERE username=?",
                (hash_b64, salt_b64, "rehash_user"),
            )

        creds_before = account_repo.get_credentials(account.id)
        assert creds_before[2] == 200_000

        # Authenticate → triggers transparent rehash to 600k
        auth_service.authenticate("rehash_user", password, "teacher")

        creds_after = account_repo.get_credentials(account.id)
        assert creds_after[2] == 600_000
