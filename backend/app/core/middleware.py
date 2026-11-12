"""Request middleware: request IDs, timing logs, security headers and body size limit.

Written as plain ASGI middleware (not BaseHTTPMiddleware) so it adds no task
overhead and works with streaming responses.
"""

import json
import logging
import re
import time
import uuid

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import reset_request_id, set_request_id

logger = logging.getLogger("syncforge.request")

REQUEST_ID_HEADER = b"x-request-id"
# Accept a caller-supplied ID only if it is short and safe to put in logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# Sent with every response. The API returns JSON only, so it never needs to be framed,
# sniffed as another content type, or leak its URL in a Referer header.
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
]
# API responses carry personal data and must not be stored by browsers or proxies. The
# strict content security policy is for JSON; /docs (Swagger UI) loads scripts, so it is
# applied to /api only.
_API_HEADERS = [
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._resolve_request_id(scope)
        # request.state.request_id - readable by exception handlers outside this middleware.
        scope.setdefault("state", {})["request_id"] = request_id
        token = set_request_id(request_id)

        is_api = scope["path"].startswith("/api/")
        status_code = 500  # stays 500 if the app raises before sending a response
        start = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
                present = {name.lower() for name, _ in headers}
                extra = _SECURITY_HEADERS + (_API_HEADERS if is_api else [])
                headers.extend(h for h in extra if h[0] not in present)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            reset_request_id(token)

    @staticmethod
    def _resolve_request_id(scope: Scope) -> str:
        for name, value in scope["headers"]:
            if name == REQUEST_ID_HEADER:
                candidate = value.decode("latin-1")
                if _VALID_REQUEST_ID.match(candidate):
                    return candidate
                break
        return uuid.uuid4().hex


class BodySizeLimitMiddleware:
    """Refuses request bodies larger than `max_bytes` with 413 payload_too_large.

    A declared Content-Length over the limit is refused before the body is read; a body
    without one (chunked) is counted while it streams and refused when it passes the
    limit, so an oversized upload is never held in memory in full.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._refuse(scope, send)
                    return
                break

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises HTTPException from body reading, so this reaches the
                    # error handler and becomes the standard error response.
                    raise HTTPException(413, self._message())
            return message

        await self.app(scope, limited_receive, send)

    def _message(self) -> str:
        return f"The request body is larger than the limit of {self.max_bytes} bytes."

    async def _refuse(self, scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": self._message(),
                    "details": None,
                    "request_id": request_id,
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
