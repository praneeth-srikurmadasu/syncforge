"""Credential encryption: round trip, tamper detection, key rotation, configuration."""

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.security.encryption import (
    CredentialCipher,
    CredentialDecryptionError,
    EncryptionNotConfiguredError,
    fingerprint,
)

SECRETS = {"token": "xoxp-super-secret-token-123456", "client_id": "abc"}


def test_round_trip_and_ciphertext_hides_the_secret() -> None:
    cipher = CredentialCipher([Fernet.generate_key().decode()])

    token = cipher.encrypt(SECRETS)

    assert "super-secret" not in token
    assert cipher.decrypt(token) == SECRETS


def test_tampered_ciphertext_is_rejected() -> None:
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    token = cipher.encrypt(SECRETS)
    tampered = token[:-5] + ("A" if token[-5] != "A" else "B") + token[-4:]

    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt(tampered)


def test_wrong_key_cannot_decrypt() -> None:
    token = CredentialCipher([Fernet.generate_key().decode()]).encrypt(SECRETS)

    with pytest.raises(CredentialDecryptionError):
        CredentialCipher([Fernet.generate_key().decode()]).decrypt(token)


def test_key_rotation_keeps_old_values_readable() -> None:
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    old_token = CredentialCipher([old_key]).encrypt(SECRETS)

    rotated = CredentialCipher([new_key, old_key])  # new key first: used for encryption
    new_token = rotated.encrypt(SECRETS)

    assert rotated.decrypt(old_token) == SECRETS
    assert CredentialCipher([new_key]).decrypt(new_token) == SECRETS
    with pytest.raises(CredentialDecryptionError):
        CredentialCipher([old_key]).decrypt(new_token)


def test_invalid_key_is_reported_clearly() -> None:
    with pytest.raises(ValueError, match="Fernet"):
        CredentialCipher(["not-a-valid-key"])


def test_from_settings_supports_comma_separated_keys() -> None:
    first, second = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings = Settings(connector_encryption_key=f"{first}, {second}")

    token = CredentialCipher([second]).encrypt(SECRETS)

    assert CredentialCipher.from_settings(settings).decrypt(token) == SECRETS


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_or_blank_key_is_a_clear_503(key: str | None) -> None:
    # A blank value is what `CONNECTOR_ENCRYPTION_KEY=` in .env.example produces.
    with pytest.raises(EncryptionNotConfiguredError) as caught:
        CredentialCipher.from_settings(Settings(connector_encryption_key=key))

    assert caught.value.status_code == 503
    assert caught.value.code == "encryption_not_configured"


@pytest.mark.parametrize("key", [None, ""])
def test_production_requires_an_encryption_key(key: str | None) -> None:
    with pytest.raises(ValueError, match="CONNECTOR_ENCRYPTION_KEY"):
        Settings(
            app_env="production",
            jwt_secret_key="a-real-production-jwt-secret-0123456789",
            postgres_password="a-real-production-password",
            connector_encryption_key=key,
        )


@pytest.mark.parametrize(
    ("secret", "expected"),
    [("xoxp-1234567890-abcd", "...abcd"), ("short", "...****"), ("", "...****")],
)
def test_fingerprint_reveals_at_most_four_characters(secret: str, expected: str) -> None:
    assert fingerprint(secret) == expected
