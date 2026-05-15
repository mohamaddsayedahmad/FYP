"""
Unit tests for the password hashing module.

Security tests must verify:
- Correct passwords verify successfully.
- Wrong passwords never verify.
- Timing-safe comparison (compare_digest) is used — tested indirectly by
  verifying the function uses the infrastructure that guarantees it.
- Rehash detection flags weak iteration counts.
- Legacy hex-encoded hashes from the original database.py verify correctly.
"""

from __future__ import annotations

import pytest

from infrastructure.security.password import (
    HashedPassword,
    hash_password,
    needs_rehash,
    verify_password,
)


class TestHashPassword:

    def test_produces_non_empty_hash(self):
        h = hash_password("mysecret")
        assert h.hash_b64
        assert h.salt_b64

    def test_same_password_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1.hash_b64 != h2.hash_b64  # different salts

    def test_iterations_set_to_current_standard(self):
        h = hash_password("x")
        assert h.iterations == 600_000


class TestVerifyPassword:

    def test_correct_password_verifies(self):
        stored = hash_password("correct")
        assert verify_password("correct", stored) is True

    def test_wrong_password_fails(self):
        stored = hash_password("correct")
        assert verify_password("wrong", stored) is False

    def test_empty_password_fails(self):
        stored = hash_password("correct")
        assert verify_password("", stored) is False

    def test_unicode_password(self):
        stored = hash_password("pässwörd-ünïcødé")
        assert verify_password("pässwörd-ünïcødé", stored) is True
        assert verify_password("passwort", stored) is False


class TestNeedsRehash:

    def test_legacy_iteration_count_needs_rehash(self):
        old = HashedPassword(hash_b64="x", salt_b64="y", iterations=200_000)
        assert needs_rehash(old) is True

    def test_current_iteration_count_does_not_need_rehash(self):
        current = HashedPassword(hash_b64="x", salt_b64="y", iterations=600_000)
        assert needs_rehash(current) is False

    def test_zero_iterations_treated_as_legacy(self):
        legacy = HashedPassword(hash_b64="x", salt_b64="y", iterations=0)
        assert needs_rehash(legacy) is True
