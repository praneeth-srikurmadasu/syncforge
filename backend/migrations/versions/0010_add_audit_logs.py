"""Add audit_logs: the append-only record of who did what (app/models/audit.py).

A trigger makes the table append-only in the database itself. UPDATE is refused, with one
exception: the foreign key's ON DELETE SET NULL, when a user account is deleted, may
clear `actor_user_id` and change nothing else. DELETE is refused unless the transaction
has run `SET LOCAL syncforge.allow_audit_delete = 'on'` (reserved for a future retention
job).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARD = """
CREATE FUNCTION audit_logs_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND current_setting('syncforge.allow_audit_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    -- ON DELETE SET NULL of the actor: only actor_user_id may change, and only to NULL.
    IF TG_OP = 'UPDATE'
       AND OLD.actor_user_id IS NOT NULL AND NEW.actor_user_id IS NULL
       AND ROW(NEW.id, NEW.organization_id, NEW.actor_type, NEW.action, NEW.resource_type,
               NEW.resource_id, NEW.outcome, NEW.details, NEW.request_id, NEW.created_at)
           IS NOT DISTINCT FROM
           ROW(OLD.id, OLD.organization_id, OLD.actor_type, OLD.action, OLD.resource_type,
               OLD.resource_id, OLD.outcome, OLD.details, OLD.request_id, OLD.created_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_logs is append-only (% refused)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER audit_logs_append_only
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();
"""


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", _enum("user", "system", name="audit_actor_type"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", _enum("success", "failure", name="audit_outcome"), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_organization_id_created_at", "audit_logs", ["organization_id", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_organization_id_resource",
        "audit_logs",
        ["organization_id", "resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_logs_organization_id_action", "audit_logs", ["organization_id", "action"]
    )
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION audit_logs_append_only()")
    op.drop_table("audit_logs")
