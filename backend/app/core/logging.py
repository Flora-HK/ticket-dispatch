import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

REQUEST_LOGGER_NAME = "app.request"
request_logger = logging.getLogger(REQUEST_LOGGER_NAME)
_configured = False


class JsonLogFormatter(logging.Formatter):
    """Serialize application logs as one JSON object per line."""

    _EXTRA_FIELDS = (
        "event",
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "exception_type",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )


def configure_logging() -> None:
    """Configure idempotent JSON logging for this application."""

    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    request_logger.propagate = False
    _configured = True
