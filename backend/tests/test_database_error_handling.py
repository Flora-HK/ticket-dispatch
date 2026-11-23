import asyncio
import json
import uuid

import pytest
from fastapi import Request
from psycopg.errors import (
    DeadlockDetected,
    LockNotAvailable,
    QueryCanceled,
)
from psycopg.errors import OperationalError as PsycopgOperationalError
from sqlalchemy.exc import OperationalError

from app.api.deps import get_db
from app.core.errors import database_error_handler
from app.main import app


def _request_with_id(request_id: uuid.UUID) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/tickets",
            "headers": [],
            "query_string": b"",
        }
    )
    request.state.request_id = request_id
    return request


@pytest.mark.parametrize(
    ("original", "expected_code"),
    [
        (LockNotAvailable("canceling statement due to lock timeout"), "DATABASE_LOCK_TIMEOUT"),
        (QueryCanceled("canceling statement due to statement timeout"), "DATABASE_STATEMENT_TIMEOUT"),
        (DeadlockDetected("deadlock detected"), "DATABASE_RETRYABLE_TRANSACTION"),
        (PsycopgOperationalError("connection refused"), "SERVICE_UNAVAILABLE"),
    ],
)
def test_database_operational_errors_return_retryable_contract(
    original: Exception,
    expected_code: str,
) -> None:
    request_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    error = OperationalError("SELECT 1", {}, original)

    response = asyncio.run(
        database_error_handler(
            _request_with_id(request_id),
            error,
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert response.headers["X-Request-ID"] == str(request_id)
    assert response.headers["Retry-After"] == "1"
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["request_id"] == str(request_id)
    assert payload["error"]["details"] == {"retryable": True}


def test_app_maps_database_lock_timeout_to_retryable_response(client) -> None:
    def failing_database_session():
        raise OperationalError(
            "SELECT 1",
            {},
            LockNotAvailable("canceling statement due to lock timeout"),
        )
        yield

    app.dependency_overrides[get_db] = failing_database_session
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    payload = response.json()
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert payload["error"]["code"] == "DATABASE_LOCK_TIMEOUT"
    assert payload["error"]["details"] == {"retryable": True}
