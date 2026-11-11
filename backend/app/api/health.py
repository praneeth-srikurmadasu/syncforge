"""Liveness and readiness probes.

/health - is the process up? Never touches dependencies, so a slow database
          does not cause an orchestrator to restart a healthy API process.
/ready  - can the API serve traffic? Checks the database; returns 503 if not.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.core.database import check_database, get_engine
from app.core.errors import ServiceUnavailableError

logger = logging.getLogger("syncforge.health")

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="syncforge-api", version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"description": "A dependency is unavailable"}},
)
def ready(engine: Annotated[Engine, Depends(get_engine)]) -> ReadinessResponse:
    try:
        check_database(engine)
    except SQLAlchemyError as exc:
        # Log the error type only; driver messages can contain connection details.
        logger.warning("readiness check failed", extra={"error_type": type(exc).__name__})
        raise ServiceUnavailableError(
            "Database is not reachable.", code="not_ready", details={"database": "unreachable"}
        ) from exc
    return ReadinessResponse(status="ready", checks={"database": "ok"})
