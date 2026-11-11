"""Request context middleware: request IDs and request timing logs.

Written as plain ASGI middleware (not BaseHTTPMiddleware) so it adds no task
overhead and works with streaming responses.
"""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import reset_request_id, set_request_id

logger = logging.getLogger("syncforge.request")

REQUEST_ID_HEADER = b"x-request-id"
# Accept a caller-supplied ID only if it is short and safe to put in logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


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

        status_code = 500  # stays 500 if the app raises before sending a response
        start = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
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
