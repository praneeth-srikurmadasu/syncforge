"""Tests for the Super Admin bootstrap command."""

import pytest
from sqlalchemy.orm import Session

from app.cli import create_superadmin
from app.security.passwords import verify_password
from tests.factories import create_user


def test_creates_new_superadmin(db_session: Session) -> None:
    user = create_superadmin(
        db_session, email=" Root@Example.com ", full_name="Root", password="a-strong-password-1"
    )

    assert user.email == "root@example.com"
    assert user.is_superadmin is True
    assert verify_password("a-strong-password-1", user.password_hash)[0] is True


def test_promotes_existing_user_without_changing_password(db_session: Session) -> None:
    existing = create_user(db_session, email="ops@example.com", is_active=False)
    original_hash = existing.password_hash

    user = create_superadmin(db_session, email="ops@example.com", full_name="Ops", password=None)

    assert user.id == existing.id
    assert user.is_superadmin is True
    assert user.is_active is True
    assert user.password_hash == original_hash


def test_rejects_weak_password_for_new_superadmin(db_session: Session) -> None:
    with pytest.raises(ValueError, match="12-128"):
        create_superadmin(db_session, email="new@example.com", full_name="New", password="short")
