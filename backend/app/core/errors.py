"""Application errors and the single error response format.

Every error response has the same shape:

    {"error": {"code": "not_found", "message": "...", "details": null, "request_id": "..."}}

Clients branch on the stable ``code``; ``message`` is human-readable.
Unexpected exceptions never leak internals - they return a generic 500.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = logging.getLogger("syncforge.errors")


class AppError(Exception):
    """Base class for expected, client-facing errors."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details
        self.headers = headers


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_failed"

    def __init__(self, message: str = "Authentication required.", **kwargs: Any) -> None:
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnprocessableError(AppError):
    """Well-formed input that breaks a business rule (e.g. a terminated manager)."""

    status_code = 422
    code = "unprocessable"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


_HTTP_STATUS_CODES = {
    400: "bad_request",
    401: "authentication_failed",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    429: "rate_limited",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or get_request_id()


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": _request_id(request),
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            request, exc.status_code, exc.code, exc.message, exc.details, exc.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(request, exc.status_code, code, message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Report the field and reason only - never echo the submitted value,
        # which could be a password.
        details = [
            {
                "field": ".".join(str(part) for part in err["loc"] if part != "body"),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        return error_response(
            request, 422, "validation_error", "Request validation failed.", details
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception", extra={"path": request.url.path})
        request_id = _request_id(request)
        # This handler runs outside RequestContextMiddleware, so add the header here.
        headers = {"X-Request-ID": request_id} if request_id else None
        return error_response(
            request, 500, "internal_error", "An unexpected error occurred.", headers=headers
        )
