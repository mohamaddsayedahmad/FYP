"""
Authentication service.

Responsibilities:
- Verify credentials and return an authenticated Account entity.
- Create new accounts with properly hashed passwords.
- Enforce password rehashing when the stored iteration count is below the
  current OWASP recommendation (transparent upgrade on login).
- Ensure default admin and teacher accounts exist at startup.

No JWT logic here — that belongs in the API transport layer.
"""

from __future__ import annotations

from typing import Optional

from core.entities import Account
from core.exceptions import AuthenticationError, NotFoundError
from core.interfaces import IAccountRepository
from infrastructure.security.password import (
    HashedPassword,
    hash_password,
    needs_rehash,
    verify_password,
)


class AuthService:

    def __init__(self, account_repo: IAccountRepository) -> None:
        self._accounts = account_repo

    def authenticate(self, username: str, password: str, role: str) -> Account:
        """
        Verify credentials and return the authenticated Account.
        Raises AuthenticationError on failure.

        Performs transparent password rehash when iteration count is stale
        so the security upgrade is invisible to the user.
        """
        account = self._accounts.get_by_username_and_role(username, role)
        if not account:
            raise AuthenticationError("invalid credentials")

        credentials = self._accounts.get_credentials(account.id)
        if not credentials:
            raise AuthenticationError("invalid credentials")

        hash_b64, salt_b64, iterations = credentials
        stored = HashedPassword(
            hash_b64=hash_b64,
            salt_b64=salt_b64,
            iterations=iterations,
        )

        if not verify_password(password, stored):
            raise AuthenticationError("invalid credentials")

        if needs_rehash(stored):
            self._rehash_account(account.id, password, account.username, role)

        return account

    def create_account(
        self,
        username: str,
        password: str,
        role: str,
        student_uid: Optional[str] = None,
        name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Account:
        account = Account(
            username=username,
            role=role,
            student_uid=student_uid,
            name=name,
            email=email,
        )
        hashed = hash_password(password)
        return self._accounts.save(account, hashed.hash_b64, hashed.salt_b64)

    def username_exists(self, username: str) -> bool:
        """Return True if any active account (any role) already holds this username."""
        return self._accounts.username_exists(username)

    def ensure_default_accounts(self) -> None:
        """
        Ensure at least one admin and one teacher exist so a fresh install is
        not locked out. Prints a warning if these defaults are still in place.
        """
        admins = self._accounts.get_active_by_role("admin")
        if not admins:
            self.create_account("admin", "admin123", "admin")
            import warnings
            warnings.warn(
                "Default admin account created (admin/admin123). "
                "Change this password immediately after first login.",
                RuntimeWarning, stacklevel=2,
            )

        teachers = self._accounts.get_active_by_role("teacher")
        if not teachers:
            self.create_account("teacher", "teacher123", "teacher")
            import warnings
            warnings.warn(
                "Default teacher account created (teacher/teacher123). "
                "Change this password after first login.",
                RuntimeWarning, stacklevel=2,
            )

    def _rehash_account(
        self, account_id: int, plaintext: str, username: str, role: str
    ) -> None:
        hashed = hash_password(plaintext)
        account = Account(username=username, role=role)
        account.id = account_id
        self._accounts.save(account, hashed.hash_b64, hashed.salt_b64)
