"""Add security_events: append-only record of sign-ins, failures, sign-outs and refusals.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENTS = (
    "login_succeeded",
    "login_failed",
    "login_rate_limited",
    "logout",
    "registered",
    "registration_rate_limited",
)

GUARD = """
CREATE FUNCTION security_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND current_setting('syncforge.allow_security_event_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'security_events is append-only (% refused)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER security_events_append_only
BEFORE UPDATE OR DELETE ON security_events
FOR EACH ROW EXECUTE FUNCTION security_events_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "event",
            sa.Enum(
                *EVENTS,
                name="security_event_type",
                native_enum=False,
                create_constraint=True,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("account_hash", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=30), nullable=True),
        sa.Column("client_ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index(
        "ix_security_events_user_id_created_at", "security_events", ["user_id", "created_at"]
    )
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER security_events_append_only ON security_events")
    op.execute("DROP FUNCTION security_events_append_only()")
    op.drop_index("ix_security_events_created_at", table_name="security_events")
    op.drop_index("ix_security_events_user_id_created_at", table_name="security_events")
    op.drop_table("security_events")
