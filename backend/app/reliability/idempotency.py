"""Idempotency keys for SyncForge's own create endpoints (incoming requests).

How a request with `Idempotency-Key: <key>` is handled:

1. `lookup()`: is there an unexpired record for (organization, user, key)?
   * same endpoint and body -> return the stored response; nothing is executed again;
   * different endpoint or body -> 422 `idempotency_key_reused` (a client bug: reusing
     a key for a new request would otherwise silently return the old result).
2. No record: the endpoint runs normally and `stage()` adds the record to the session
   just before the service commits, so the change and its record commit together. A
   crash can never leave "employee created, no record" (the retry would create a
   duplicate) or "record, no employee".
3. Two identical requests at the same moment: both miss in step 1 and both try to
   commit. The unique constraints serialize them - the second waits for the first, then
   fails (duplicate employee number, or duplicate key). `after_conflict()` then finds the
   first request's record and the second caller receives the same response, as if it
   had arrived later.

Only successful responses are stored. A request that failed validation may be corrected
and sent again with the same key.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import UnprocessableError
from app.models import IdempotencyRecord

REPLAY_HEADER = "Idempotent-Replayed"


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict[str, Any]


def request_hash(endpoint: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{endpoint}\n{canonical}".encode()).hexdigest()


class IdempotencyStore:
    def __init__(
        self,
        session: Session,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        key: str,
        endpoint: str,
        body: dict[str, Any],
        ttl_hours: int,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.user_id = user_id
        self.key = key
        self.endpoint = endpoint
        self.hash = request_hash(endpoint, body)
        self.ttl = timedelta(hours=ttl_hours)

    def lookup(self) -> StoredResponse | None:
        record = self._record()
        if record is None:
            return None
        if record.expires_at <= datetime.now(UTC):
            self.session.delete(record)  # expired: the key may be used afresh
            self.session.commit()
            return None
        if record.endpoint != self.endpoint or record.request_hash != self.hash:
            raise UnprocessableError(
                "This Idempotency-Key was already used for a different request. "
                "Use a new key for a new request.",
                code="idempotency_key_reused",
            )
        return StoredResponse(record.response_status, record.response_body)

    def stage(self, status_code: int, body: dict[str, Any], resource_id: uuid.UUID) -> None:
        """Add the record to the session; the caller's commit makes it durable."""
        self.session.add(
            IdempotencyRecord(
                organization_id=self.organization_id,
                user_id=self.user_id,
                idempotency_key=self.key,
                endpoint=self.endpoint,
                request_hash=self.hash,
                response_status=status_code,
                response_body=body,
                resource_id=resource_id,
                expires_at=datetime.now(UTC) + self.ttl,
            )
        )

    def after_conflict(self) -> StoredResponse | None:
        """The request failed on a uniqueness conflict: did an identical request win?"""
        return self.lookup()

    def _record(self) -> IdempotencyRecord | None:
        return self.session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == self.organization_id,
                IdempotencyRecord.user_id == self.user_id,
                IdempotencyRecord.idempotency_key == self.key,
            )
        )


def purge_expired(session: Session, *, now: datetime | None = None) -> int:
    result = session.execute(
        delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= (now or datetime.now(UTC)))
    )
    session.commit()
    return result.rowcount or 0
