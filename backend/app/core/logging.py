"""Structured JSON logging.

Every log line is one JSON object with a timestamp, level, logger, message and the
current request ID, plus any fields passed through ``extra={...}``. This makes logs
searchable by request ID (and later by event ID and correlation ID).
"""

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.request_context import get_request_id

# Attributes every LogRecord has; anything else came from `extra=` and is emitted as a field.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
    "color_message",  # uvicorn adds an ANSI-coloured duplicate of the message
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    # Route uvicorn's own logs through the JSON handler.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers[:] = []
        uvicorn_logger.propagate = True
    # Our middleware logs every request with timing; uvicorn's access log would duplicate it.
    logging.getLogger("uvicorn.access").disabled = True
