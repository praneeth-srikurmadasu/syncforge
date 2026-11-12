"""Behaviour shared by every mock service: failure injection and idempotency keys.

A test (or a person running the demo) queues faults through the control API:

    POST /_mock/faults  {"kind": "status", "status": 503, "count": 2}
    POST /_mock/faults  {"kind": "rate_limit", "retry_after": 2, "count": 1}
    POST /_mock/faults  {"kind": "timeout", "delay_seconds": 5, "count": 1}
    POST /_mock/faults  {"kind": "status", "status": 500, "count": 1, "path_prefix": "/scim"}
    DELETE /_mock/faults          clear queued faults
    POST /_mock/reset             clear faults, stored users and the request log
    GET  /_mock/state             queued faults, user count and the request log

Each fault applies to the next `count` matching API requests, then disappears. Control
endpoints are never affected by faults and require no authentication: the mocks are
for local use only and must never be exposed publicly.

Idempotency keys (POST only). A POST carrying an `Idempotency-Key` header is executed
once per (path, key). Repeating it with the same body returns the stored response again
(header `Idempotent-Replayed: true`) without executing it; the same key with a
different body is refused with 422; a repeat that arrives while the first request is
still running gets 409. Only successful (2xx) responses are stored - a failed request
may be repeated with the same key. This follows the convention popularised by payment
APIs (and the IETF "Idempotency-Key" HTTP header draft). The REAL Slack SCIM and Google
Directory APIs do not document such a header: see docs/13 for what SyncForge relies on
there.
"""

import asyncio
import hashlib
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

CONTROL_PREFIX = "/_mock"


class FaultSpec(BaseModel):
    kind: Literal["status", "rate_limit", "timeout"]
    count: int = Field(default=1, ge=1, le=1000)
    status: int = Field(default=503, ge=400, le=599)
    retry_after: int | None = Field(default=None, ge=0, le=3600)
    delay_seconds: float = Field(default=5.0, ge=0, le=60)
    path_prefix: str = "/"


@dataclass
class MockState:
    """In-memory state of one mock service. Thread-safe enough for tests and demos."""

    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    faults: list[FaultSpec] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    # (path, key) -> {"fingerprint", "status": None while running, "body"}
    idempotency: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def take_fault(self, path: str) -> FaultSpec | None:
        with self.lock:
            for fault in self.faults:
                if path.startswith(fault.path_prefix):
                    fault.count -= 1
                    if fault.count == 0:
                        self.faults.remove(fault)
                    return fault.model_copy()
        return None

    def reset(self) -> None:
        with self.lock:
            self.users.clear()
            self.faults.clear()
            self.requests.clear()
            self.idempotency.clear()


def error_body_default(status: int, message: str) -> dict[str, Any]:
    return {"error": message, "status": status}


def install(
    app: FastAPI,
    state: MockState,
    *,
    error_body: Callable[[int, str], dict[str, Any]] = error_body_default,
    on_reset: Callable[[], None] | None = None,
) -> None:
    """Add the fault middleware, the request log and the /_mock control API to `app`."""

    @app.middleware("http")
    async def inject_faults(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path.startswith(CONTROL_PREFIX):
            return await call_next(request)

        fault = state.take_fault(path)
        replayed = False
        if fault is None:
            response, replayed = await _with_idempotency(request, call_next)
        elif fault.kind == "timeout":
            # Longer than the client's read timeout: the client gives up, but the request is
            # still executed - exactly the case idempotency keys exist for.
            response, replayed = await _with_idempotency(
                request, call_next, delay_seconds=fault.delay_seconds
            )
        elif fault.kind == "rate_limit":
            headers = {}
            if fault.retry_after is not None:
                headers["Retry-After"] = str(fault.retry_after)
            response = JSONResponse(
                error_body(429, "Rate limit exceeded (simulated)."),
                status_code=429,
                headers=headers,
            )
        else:
            response = JSONResponse(
                error_body(fault.status, f"Simulated failure ({fault.status})."),
                status_code=fault.status,
            )
        # Method, path and status only - never bodies or headers (they carry tokens).
        with state.lock:
            state.requests.append(
                {
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "idempotent_replay": replayed,
                }
            )
        return response

    async def _with_idempotency(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        *,
        delay_seconds: float = 0.0,
    ) -> tuple[Response, bool]:
        """Execute the request once per (path, key). `delay_seconds` simulates a slow
        request: the key is already taken while it runs."""
        key = request.headers.get("idempotency-key")
        if request.method != "POST" or not key:
            await asyncio.sleep(delay_seconds)
            return await call_next(request), False
        slot = (request.url.path, key)
        fingerprint = hashlib.sha256(await request.body()).hexdigest()
        with state.lock:
            stored = state.idempotency.get(slot)
            if stored is None:
                state.idempotency[slot] = {"fingerprint": fingerprint, "status": None}
        if stored is not None:
            if stored["fingerprint"] != fingerprint:
                body = error_body(422, "idempotency_key_reused")
                return JSONResponse(body, status_code=422), False
            if stored["status"] is None:
                body = error_body(409, "idempotency_key_in_use")
                return JSONResponse(body, status_code=409), False
            replay = Response(
                content=stored["body"],
                status_code=stored["status"],
                media_type="application/json",
                headers={"Idempotent-Replayed": "true"},
            )
            return replay, True

        try:
            await asyncio.sleep(delay_seconds)
            response = await call_next(request)
            content = b"".join([chunk async for chunk in response.body_iterator])
        except BaseException:
            with state.lock:
                state.idempotency.pop(slot, None)
            raise
        with state.lock:
            if 200 <= response.status_code < 300:
                state.idempotency[slot] = {
                    "fingerprint": fingerprint,
                    "status": response.status_code,
                    "body": content,
                }
            else:  # failures are not remembered: the client may try again
                state.idempotency.pop(slot, None)
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=content, status_code=response.status_code, headers=headers), False

    control = APIRouter(prefix=CONTROL_PREFIX, tags=["mock control"])

    @control.post("/faults", status_code=201)
    def add_fault(spec: FaultSpec) -> dict[str, Any]:
        with state.lock:
            state.faults.append(spec)
            return {"queued": len(state.faults)}

    @control.delete("/faults", status_code=204)
    def clear_faults() -> Response:
        with state.lock:
            state.faults.clear()
        return Response(status_code=204)

    @control.post("/reset", status_code=204)
    def reset() -> Response:
        state.reset()
        if on_reset is not None:
            on_reset()
        return Response(status_code=204)

    @control.get("/state")
    def get_state() -> dict[str, Any]:
        with state.lock:
            return {
                "users": len(state.users),
                "idempotency_keys": len(state.idempotency),
                "faults": [fault.model_dump() for fault in state.faults],
                "requests": list(state.requests),
            }

    app.include_router(control)
