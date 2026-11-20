"""VS8 健康检查、OpenAPI 固定和 Item 退役验收。"""

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

import app.models as model_module
from app.core.config import settings
from app.core.db import engine
from app.main import app

CONTRACT_SNAPSHOT = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"

EXPECTED_OPERATIONS = {
    ("POST", "/api/v1/login/access-token"): "auth-login_access_token",
    ("GET", "/api/v1/users/me"): "users-read_user_me",
    ("PATCH", "/api/v1/users/me"): "users-update_user_me",
    ("GET", "/api/v1/users"): "users-read_users",
    ("POST", "/api/v1/users"): "users-create_user",
    ("GET", "/api/v1/users/{user_id}"): "users-read_user_by_id",
    ("PATCH", "/api/v1/users/{user_id}"): "users-update_user",
    ("PUT", "/api/v1/users/{user_id}/roles"): "users-replace_roles",
    ("GET", "/api/v1/teams"): "teams-read_teams",
    ("GET", "/api/v1/teams/{team_id}"): "teams-read_team",
    ("POST", "/api/v1/teams"): "teams-create_team",
    ("PATCH", "/api/v1/teams/{team_id}"): "teams-update_team",
    ("GET", "/api/v1/teams/{team_id}/members"): "teams-read_team_members",
    ("PUT", "/api/v1/teams/{team_id}/members/{user_id}"): "teams-upsert_member",
    ("DELETE", "/api/v1/teams/{team_id}/members/{user_id}"): "teams-delete_member",
    ("GET", "/api/v1/tickets"): "tickets-read_tickets",
    ("POST", "/api/v1/tickets"): "tickets-create_ticket",
    ("GET", "/api/v1/tickets/{ticket_id}"): "tickets-read_ticket",
    ("PATCH", "/api/v1/tickets/{ticket_id}"): "tickets-update_ticket",
    ("GET", "/api/v1/tickets/{ticket_id}/comments"): "comments-read_comments",
    ("POST", "/api/v1/tickets/{ticket_id}/comments"): "comments-create_comment",
    (
        "GET",
        "/api/v1/tickets/{ticket_id}/assignments",
    ): "assignments-get_assignment_history",
    (
        "GET",
        "/api/v1/tickets/{ticket_id}/assignment",
    ): "assignments-get_active_assignment",
    (
        "GET",
        "/api/v1/tickets/{ticket_id}/dispatch-candidates",
    ): "assignments-get_dispatch_candidates",
    (
        "POST",
        "/api/v1/tickets/{ticket_id}/dispatch",
    ): "assignments-dispatch_ticket",
    (
        "POST",
        "/api/v1/assignments/{assignment_id}/accept",
    ): "assignments-accept_current_assignment",
    (
        "POST",
        "/api/v1/assignments/{assignment_id}/reject",
    ): "assignments-reject_current_assignment",
    (
        "POST",
        "/api/v1/assignments/{assignment_id}/complete",
    ): "assignments-complete_current_assignment",
    ("POST", "/api/v1/tickets/{ticket_id}/actions/close"): "tickets-close_ticket",
    ("POST", "/api/v1/tickets/{ticket_id}/actions/reopen"): "tickets-reopen_ticket",
    ("GET", "/api/v1/tickets/{ticket_id}/timeline"): "tickets-read_timeline",
    ("GET", "/api/v1/admin/audit-logs"): "audit-read_audit_logs",
    ("GET", "/api/v1/notifications"): "notifications-read_notifications",
    (
        "GET",
        "/api/v1/notifications/{notification_id}",
    ): "notifications-read_notification_detail",
    ("GET", "/api/v1/health/live"): "health-read_liveness",
    ("GET", "/api/v1/health/ready"): "health-read_readiness",
}


def _resolve_schema(spec: dict[str, object], value: dict[str, object]) -> dict[str, object]:
    reference = value.get("$ref")
    if not isinstance(reference, str):
        return value
    name = reference.rsplit("/", 1)[-1]
    schemas = spec["components"]["schemas"]  # type: ignore[index]
    schema = schemas[name]  # type: ignore[index]
    assert isinstance(schema, dict)
    return schema


def test_vs8_health_live_and_ready(client: TestClient) -> None:
    live = client.get(f"{settings.API_V1_STR}/health/live")
    assert live.status_code == 200
    assert live.json() == {
        "status": "ok",
        "service": settings.PROJECT_NAME,
    }

    ready = client.get(f"{settings.API_V1_STR}/health/ready")
    assert ready.status_code == 200
    assert ready.json() == live.json()


def test_vs8_health_ready_reports_database_failure(client: TestClient) -> None:
    failure = OperationalError(
        "SELECT 1",
        {},
        RuntimeError("database unavailable"),
    )
    with patch("app.api.routes.health.check_database", side_effect=failure):
        response = client.get(f"{settings.API_V1_STR}/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_vs8_openapi_is_frozen_to_36_typed_operations() -> None:
    spec = app.openapi()
    operations = {
        (method.upper(), path): operation
        for path, path_item in spec["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert {
        key: operation["operationId"]
        for key, operation in operations.items()
    } == EXPECTED_OPERATIONS
    assert len(operations) == 36

    assert spec["components"]["securitySchemes"]["OAuth2PasswordBearer"] == {
        "type": "oauth2",
        "flows": {
            "password": {
                "scopes": {},
                "tokenUrl": "/api/v1/login/access-token",
            }
        },
    }

    for (method, path), operation in operations.items():
        success_codes = [
            code for code in operation["responses"] if code.startswith("2")
        ]
        assert success_codes, f"{method} {path} has no documented success response"
        for code in success_codes:
            content = operation["responses"][code].get("content")
            assert content, f"{method} {path} {code} has no response model"
            assert "schema" in next(iter(content.values()))

        error_responses = {
            code: response
            for code, response in operation["responses"].items()
            if code.startswith(("4", "5"))
        }
        if path != "/api/v1/health/live":
            assert error_responses, f"{method} {path} has no error response"
        for response in error_responses.values():
            content = response.get("content", {})
            schema = content.get("application/json", {}).get("schema", {})
            resolved = _resolve_schema(spec, schema)
            assert "error" in resolved.get("properties", {})

        request_body = operation.get("requestBody")
        if request_body is not None:
            content = request_body["content"]
            body_schema = next(iter(content.values()))["schema"]
            resolved = _resolve_schema(spec, body_schema)
            assert "status" not in resolved.get("properties", {})

    assert "Item" not in spec["components"]["schemas"]
    assert not any(path.startswith("/api/v1/items") for path in spec["paths"])


def test_vs8_openapi_matches_committed_snapshot() -> None:
    assert CONTRACT_SNAPSHOT.exists()
    committed = json.loads(CONTRACT_SNAPSHOT.read_text(encoding="utf-8"))
    assert committed == app.openapi()


def test_vs8_item_runtime_and_database_are_retired(client: TestClient) -> None:
    assert not hasattr(model_module, "Item")
    assert not any(
        path.startswith("/api/v1/items")
        for path in app.openapi()["paths"]
    )
    assert "item" not in inspect(engine).get_table_names()

    response = client.get(f"{settings.API_V1_STR}/items/")
    assert response.status_code == 404
