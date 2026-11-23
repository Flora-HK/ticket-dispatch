import json
import logging
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.logging import JsonLogFormatter, request_logger
from app.main import app


class CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_unhandled_exception_returns_safe_contract_response() -> None:
    request_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    handler = CapturingHandler()
    previous_level = request_logger.level
    request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    client = TestClient(app, raise_server_exceptions=False)

    try:
        with patch(
            "app.api.routes.health.check_database",
            side_effect=RuntimeError("secret database diagnostic"),
        ):
            response = client.get(
                "/api/v1/health/ready",
                headers={"X-Request-ID": str(request_id)},
            )
    finally:
        request_logger.removeHandler(handler)
        request_logger.setLevel(previous_level)

    payload = response.json()
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == str(request_id)
    assert payload["error"] == {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected error occurred.",
        "request_id": str(request_id),
        "details": None,
    }
    assert "secret database diagnostic" not in response.text
    exception_log = next(
        item
        for item in handler.records
        if getattr(item, "event", None) == "unhandled_exception"
    )
    request_log = next(
        item
        for item in handler.records
        if getattr(item, "event", None) == "request_completed"
    )
    assert exception_log.request_id == str(request_id)
    assert exception_log.exception_type == "RuntimeError"
    assert request_log.status_code == 500
    assert request_log.exception_type == "RuntimeError"


def test_request_logging_is_structured_and_excludes_request_body() -> None:
    request_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
    handler = CapturingHandler()
    previous_level = request_logger.level
    request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    client = TestClient(app)
    try:
        client.post(
            "/api/v1/login/access-token",
            content=(
                "username=admin@example.com"
                "&password=SENSITIVE-LOGIN-MARKER"
            ),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Request-ID": str(request_id),
            },
        )
    finally:
        request_logger.removeHandler(handler)
        request_logger.setLevel(previous_level)

    record = next(
        item
        for item in handler.records
        if getattr(item, "event", None) == "request_completed"
    )
    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["event"] == "request_completed"
    assert payload["request_id"] == str(request_id)
    assert payload["method"] == "POST"
    assert payload["path"] == "/api/v1/login/access-token"
    assert isinstance(payload["status_code"], int)
    assert isinstance(payload["duration_ms"], int)
    assert "SENSITIVE-LOGIN-MARKER" not in json.dumps(payload)
