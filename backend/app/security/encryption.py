"""Encryption of connector credentials at rest.

Credentials (API tokens, OAuth client secrets) are stored as one Fernet token per
connector: AES-128-CBC encryption plus an HMAC-SHA256 signature, so a modified
ciphertext is detected instead of silently decrypting to garbage.

Key rotation: CONNECTOR_ENCRYPTION_KEY may hold several comma-separated keys. The
first key encrypts new values; every key is tried for decryption (MultiFernet), so
old rows stay readable until they are re-encrypted with the new key.
"""

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ServiceUnavailableError


class EncryptionNotConfiguredError(ServiceUnavailableError):
    code = "encryption_not_configured"


class CredentialDecryptionError(AppError):
    """The stored ciphertext cannot be decrypted with any configured key."""

    status_code = 500
    code = "credentials_unreadable"


class CredentialCipher:
    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("At least one encryption key is required.")
        try:
            self._fernet = MultiFernet([Fernet(key.strip().encode()) for key in keys])
        except ValueError as exc:  # wrong length or not url-safe base64
            raise ValueError(
                "CONNECTOR_ENCRYPTION_KEY must be Fernet key(s): 32 url-safe base64-encoded bytes."
            ) from exc

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "CredentialCipher":
        settings = settings or get_settings()
        if settings.connector_encryption_key is None:
            raise EncryptionNotConfiguredError(
                "Connector credential encryption is not configured (set CONNECTOR_ENCRYPTION_KEY)."
            )
        raw = settings.connector_encryption_key.get_secret_value()
        return cls([key for key in raw.split(",") if key.strip()])

    def encrypt(self, secrets: dict[str, Any]) -> str:
        plaintext = json.dumps(secrets, sort_keys=True, separators=(",", ":"))
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> dict[str, Any]:
        try:
            plaintext = self._fernet.decrypt(token.encode())
        except InvalidToken as exc:
            raise CredentialDecryptionError(
                "Stored connector credentials cannot be decrypted with the configured keys."
            ) from exc
        return json.loads(plaintext)


def fingerprint(secret: str) -> str:
    """A non-reversible hint for the UI, e.g. '...a1b2'. Never more than 4 characters."""
    return f"...{secret[-4:]}" if len(secret) >= 12 else "...****"
