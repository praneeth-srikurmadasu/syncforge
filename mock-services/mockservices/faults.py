"""Failure injection shared by every mock service.

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
"""

import asyncio
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
        if fault is None:
            response = await call_next(request)
        elif fault.kind == "timeout":
            await asyncio.sleep(fault.delay_seconds)  # longer than the client's read timeout
            response = await call_next(request)
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
                {"method": request.method, "path": path, "status": response.status_code}
            )
        return response

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
                "faults": [fault.model_dump() for fault in state.faults],
                "requests": list(state.requests),
            }

    app.include_router(control)
