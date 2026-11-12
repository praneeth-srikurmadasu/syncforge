"""Circuit breaker per connector.

Retries protect one job from a blip. They do nothing for the external application: if
Slack is down and fifty onboarding jobs each retry five times, Slack receives 250 calls
it cannot answer, and every one of them holds a worker for up to the read timeout. The
breaker stops that.

States (row in `connector_circuits`, shared by every worker):

* CLOSED - normal. Outage-type failures (server error, timeout, network) are counted;
  any other answer - success, but also 401, 400, 404, 409, 429 - proves the
  application is reachable and resets the count. At CIRCUIT_FAILURE_THRESHOLD
  consecutive outage failures the breaker OPENS.
* OPEN - calls are refused without touching the network, with a `circuit_open` error
  whose `retry_after` is the time left. The retry engine treats it like any retryable
  failure: the job waits at least until the breaker may let a call through again.
  A refused call counts as an attempt of that job (it is recorded as one, with no HTTP
  status): this keeps the retry budget finite, so a long outage ends in the dead-letter
  queue - from where one replay restarts the work - rather than in jobs waiting forever.
* HALF_OPEN - after CIRCUIT_OPEN_SECONDS the next caller becomes the single trial call;
  everyone else is still refused. Trial succeeds -> CLOSED. Trial fails -> OPEN again
  for another period. A trial whose worker died (older than the operation timeout) is
  abandoned and the next caller becomes the trial.

A successful manual connection test (POST /connectors/{id}/test) also closes the
breaker: an administrator who has fixed something does not have to wait.

Rows are locked with SELECT ... FOR UPDATE only while the state is read or written,
never during the external call.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import audit
from app.connectors.errors import ConnectorError, ErrorCategory
from app.core.config import Settings
from app.models import AuditOutcome, CircuitState, Connector, ConnectorCircuit

logger = logging.getLogger("syncforge.circuit")

# Failures that say "the application is not working", as opposed to "it answered no".
OUTAGE_CATEGORIES = frozenset({ErrorCategory.SERVER, ErrorCategory.TIMEOUT, ErrorCategory.NETWORK})


def _now() -> datetime:
    return datetime.now(UTC)


def circuit_open_error(retry_after: float) -> ConnectorError:
    return ConnectorError(
        ErrorCategory.CIRCUIT_OPEN,
        "Calls to this application are paused after repeated failures (circuit open).",
        "circuit_open",
        retry_after=max(retry_after, 1.0),
    )


class CircuitBreaker:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.threshold = settings.circuit_failure_threshold
        self.open_for = timedelta(seconds=settings.circuit_open_seconds)
        # A trial call cannot legitimately take longer than one operation.
        self.trial_timeout = timedelta(seconds=settings.connector_operation_timeout_seconds + 5)

    def before_call(self, connector: Connector) -> None:
        """Allow the call, or raise `circuit_open`. Commits."""
        circuit = self._lock(connector)
        now = _now()
        refused_for: float | None = None
        if circuit.state is CircuitState.OPEN:
            if now < circuit.open_until:
                refused_for = (circuit.open_until - now).total_seconds()
            else:
                circuit.state = CircuitState.HALF_OPEN
                circuit.trial_started_at = now
                self._log("circuit half-open: trial call", connector, circuit)
        elif circuit.state is CircuitState.HALF_OPEN:
            trial_ends = circuit.trial_started_at + self.trial_timeout
            if now < trial_ends:
                refused_for = (trial_ends - now).total_seconds()
            else:  # the trial's worker died: this call becomes the trial
                circuit.trial_started_at = now
        self.session.commit()
        if refused_for is not None:
            raise circuit_open_error(refused_for)

    def record(self, connector: Connector, error: ConnectorError | None) -> None:
        """Record a call's result (None = success). Commits."""
        circuit = self._lock(connector)
        now = _now()
        if error is not None and error.category in OUTAGE_CATEGORIES:
            circuit.consecutive_failures += 1
            reopen = circuit.state is CircuitState.HALF_OPEN
            trip = (
                circuit.state is CircuitState.CLOSED
                and circuit.consecutive_failures >= self.threshold
            )
            if reopen or trip:
                circuit.state = CircuitState.OPEN
                circuit.opened_at = now
                circuit.open_until = now + self.open_for
                circuit.trial_started_at = None
                self._log("circuit opened", connector, circuit, level=logging.WARNING)
                self._audit(connector, circuit, "connector.circuit_opened", AuditOutcome.FAILURE)
        elif circuit.state is not CircuitState.CLOSED or circuit.consecutive_failures:
            was_closed = circuit.state is CircuitState.CLOSED
            self._close(circuit)
            if not was_closed:
                self._log("circuit closed", connector, circuit)
                self._audit(connector, circuit, "connector.circuit_closed")
        self.session.commit()

    def reset(self, connector: Connector) -> None:
        """Close the breaker (after a successful manual connection test). Commits."""
        circuit = self._lock(connector)
        if circuit.state is not CircuitState.CLOSED:
            self._close(circuit)
            self._log("circuit closed by a successful connection test", connector, circuit)
            self._audit(connector, circuit, "connector.circuit_closed", reason="connection_test")
        circuit.consecutive_failures = 0
        self.session.commit()

    # ---- helpers -------------------------------------------------------------------

    def _lock(self, connector: Connector) -> ConnectorCircuit:
        self.session.execute(
            insert(ConnectorCircuit)
            .values(connector_id=connector.id, organization_id=connector.organization_id)
            .on_conflict_do_nothing(index_elements=["connector_id"])
        )
        return self.session.scalars(
            select(ConnectorCircuit)
            .where(ConnectorCircuit.connector_id == connector.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def _audit(
        self,
        connector: Connector,
        circuit: ConnectorCircuit,
        action: str,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        *,
        reason: str | None = None,
    ) -> None:
        audit.record(
            self.session,
            organization_id=connector.organization_id,
            action=action,
            resource_type="connector",
            resource_id=connector.id,
            outcome=outcome,
            details={
                "consecutive_failures": circuit.consecutive_failures,
                "open_until": circuit.open_until,
                **({"reason": reason} if reason else {}),
            },
        )

    @staticmethod
    def _close(circuit: ConnectorCircuit) -> None:
        circuit.state = CircuitState.CLOSED
        circuit.consecutive_failures = 0
        circuit.open_until = None
        circuit.trial_started_at = None

    @staticmethod
    def _log(
        message: str,
        connector: Connector,
        circuit: ConnectorCircuit,
        *,
        level: int = logging.INFO,
    ) -> None:
        logger.log(
            level,
            message,
            extra={
                "organization_id": str(connector.organization_id),
                "connector_id": str(connector.id),
                "connector_type": connector.connector_type,
                "state": circuit.state.value,
                "consecutive_failures": circuit.consecutive_failures,
                "open_until": circuit.open_until.isoformat() if circuit.open_until else None,
            },
        )
