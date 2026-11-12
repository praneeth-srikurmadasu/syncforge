"""Tests for the Super Admin bootstrap command."""

import uuid

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
    with pytest.raises(ValueError, match="8-128"):
        create_superadmin(db_session, email="new@example.com", full_name="New", password="short")


def test_purge_expired_deletes_only_expired_rows(db_session: Session) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.cli import purge_expired_rows
    from app.models import IdempotencyRecord, RevokedToken
    from tests.factories import create_organization

    now = datetime.now(UTC)
    user = create_user(db_session)
    org = create_organization(db_session)
    db_session.add_all(
        [
            RevokedToken(jti=uuid.uuid4(), user_id=user.id, expires_at=now - timedelta(minutes=1)),
            RevokedToken(jti=uuid.uuid4(), user_id=user.id, expires_at=now + timedelta(minutes=9)),
            *[
                IdempotencyRecord(
                    organization_id=org.id,
                    user_id=user.id,
                    idempotency_key=f"key-{offset}",
                    endpoint="POST /employees",
                    request_hash="0" * 64,
                    response_status=201,
                    response_body={},
                    expires_at=now + timedelta(hours=offset),
                )
                for offset in (-1, 1)
            ],
        ]
    )
    db_session.commit()

    assert purge_expired_rows(db_session, now=now) == (1, 1)
    assert [t.expires_at > now for t in db_session.scalars(select(RevokedToken))] == [True]
    assert [r.idempotency_key for r in db_session.scalars(select(IdempotencyRecord))] == ["key-1"]
