"""Circuit breaker state, one row per connector (created on first use).

Kept in PostgreSQL rather than in each worker's memory, so every worker sees the same
state: when Slack is down, the first worker to notice protects all the others from
piling more calls onto it. The row is locked (SELECT ... FOR UPDATE) for the few
milliseconds a state check or update takes - never during the external call.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKeyConstraint, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CircuitState(enum.StrEnum):
    CLOSED = "closed"  # normal: calls go through, outage-type failures are counted
    OPEN = "open"  # too many failures: calls are refused until open_until
    HALF_OPEN = "half_open"  # one trial call is in flight; everything else waits


class ConnectorCircuit(Base):
    __tablename__ = "connector_circuits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_connector_circuits_connector_same_organization",
            ondelete="CASCADE",
        ),
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    state: Mapped[CircuitState] = mapped_column(
        Enum(
            CircuitState,
            name="circuit_state",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda states: [s.value for s in states],
        ),
        nullable=False,
        server_default=CircuitState.CLOSED.value,
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the half-open trial call started; a trial older than the operation timeout
    # belonged to a worker that died, and another trial may start.
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ConnectorCircuit {self.connector_id} {self.state}>"


class ConnectorRateWindow(Base):
    """Calls started per connector per minute: the shared counter behind
    `rate_limit_per_minute` (app/reliability/rate_limit.py)."""

    __tablename__ = "connector_rate_windows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_connector_rate_windows_connector_same_organization",
            ondelete="CASCADE",
        ),
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    def __repr__(self) -> str:
        return f"<ConnectorRateWindow {self.connector_id} {self.window_start} {self.calls}>"
