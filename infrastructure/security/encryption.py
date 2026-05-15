"""
Fernet symmetric encryption service.

Security design decisions:
1. The encryption key is loaded from the ATTENDANCE_FERNET_KEY environment
   variable — never from a file in the repository. Storing a key file next to
   the database it protects (the old encrypt.py approach) defeats the purpose
   of encryption entirely: anyone with DB access also has the key.

2. The key is resolved once at construction time and cached as a Fernet
   instance. This avoids the file I/O on every encrypt/decrypt call that the
   original implementation performed.

3. Falls back to loading from secret.key ONLY for backward compatibility with
   existing databases. Production deployments must set the env var.

Key rotation: to rotate keys, decrypt all blobs with the old key, re-encrypt
with the new key, then update the env var. Use cryptography.fernet.MultiFernet
for zero-downtime rotation.
"""

from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from core.exceptions import EncryptionError
from core.interfaces import IEncryptionService

_ENV_KEY = "ATTENDANCE_FERNET_KEY"
_LEGACY_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "secret.key")


def _load_or_generate_key() -> bytes:
    """
    Resolution order:
    1. ATTENDANCE_FERNET_KEY env var (preferred — safe for all deployments)
    2. secret.key file on disk (legacy fallback — acceptable for local dev only)
    3. Generate a new key and warn (last resort — data encrypted this session
       cannot be decrypted after restart unless the key is persisted)
    """
    raw = os.getenv(_ENV_KEY, "").strip()
    if raw:
        try:
            key = raw.encode("utf-8") if isinstance(raw, str) else raw
            Fernet(key)  # validate format
            return key
        except Exception as exc:
            raise EncryptionError(
                f"ATTENDANCE_FERNET_KEY is set but invalid: {exc}. "
                "Generate a valid key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc

    legacy = os.path.normpath(_LEGACY_KEY_FILE)
    if os.path.exists(legacy):
        with open(legacy, "rb") as fh:
            key = fh.read().strip()
        try:
            Fernet(key)
            return key
        except Exception:
            pass

    # Generate and persist to legacy file for backward compatibility
    key = Fernet.generate_key()
    try:
        with open(legacy, "wb") as fh:
            fh.write(key)
    except OSError:
        pass
    import warnings
    warnings.warn(
        "No ATTENDANCE_FERNET_KEY set and no secret.key found. "
        "A new key was generated. Set ATTENDANCE_FERNET_KEY in your .env file "
        "to ensure encrypted data persists across restarts.",
        RuntimeWarning,
        stacklevel=2,
    )
    return key


class FernetEncryptionService(IEncryptionService):
    """
    Thread-safe Fernet encryption. A single instance is safe to share across
    threads; Fernet operations do not mutate instance state.
    """

    def __init__(self, key: Optional[bytes] = None) -> None:
        resolved_key = key if key is not None else _load_or_generate_key()
        self._fernet = Fernet(resolved_key)

    def encrypt(self, plaintext: str) -> bytes:
        try:
            return self._fernet.encrypt(plaintext.encode("utf-8"))
        except Exception as exc:
            raise EncryptionError(f"encryption failed: {exc}") from exc

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            if isinstance(ciphertext, str):
                ciphertext = ciphertext.encode("utf-8")
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise EncryptionError(
                "decryption failed: token is invalid or the key has changed"
            ) from exc
        except Exception as exc:
            raise EncryptionError(f"decryption failed: {exc}") from exc


# Module-level singleton — constructed lazily on first access
_default_service: Optional[FernetEncryptionService] = None


def get_encryption_service() -> FernetEncryptionService:
    global _default_service
    if _default_service is None:
        _default_service = FernetEncryptionService()
    return _default_service
