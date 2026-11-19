"""VS6 用户、角色、Team 与成员治理验收。"""

import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.core.seed import (
    VS1_DEMO_PASSWORD,
    VS1_DISPATCHER_EMAIL,
    VS1_SUBMITTER_EMAIL,
    VS1_TEAM_NAME,
    seed_vs1_demo_data,
)
from app.main import app
from app.models import (
    Assignment,
    AuditLog,
    IdempotencyRecord,
    Team,
    User,
    UserRole,
)


@pytest.fixture()
def vs6_db(clean_db: Session) -> Generator[None]:
    with Session(engine) as setup_session:
        seed_vs1_demo_data(setup_session)
    clean_db.expunge_all()
    yield
    clean_db.rollback()
    clean_db.expunge_all()


pytestmark = pytest.mark.usefixtures("vs6_db")


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _admin_headers(client: TestClient) -> dict[str, str]:
    return _login(
        client,
        str(settings.FIRST_SUPERUSER),
        settings.FIRST_SUPERUSER_PASSWORD,
    )


def _submitter_headers(client: TestClient) -> dict[str, str]:
    return _login(client, VS1_SUBMITTER_EMAIL, VS1_DEMO_PASSWORD)


def _dispatcher_headers(client: TestClient) -> dict[str, str]:
    return _login(client, VS1_DISPATCHER_EMAIL, VS1_DEMO_PASSWORD)


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def _user(session: Session, email: str) -> User:
    user = crud.get_user_by_email(session=session, email=email)
    assert user is not None
    return user


def _team(session: Session) -> Team:
    return session.exec(select(Team).where(Team.name == VS1_TEAM_NAME)).one()


def _create_ticket(client: TestClient, team_id: uuid.UUID) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={
            **_submitter_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "team_id": str(team_id),
            "title": "治理验收工单",
            "description": "用于验证 Team 停用和成员移除。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_vs6_user_self_update_versions_audits_and_replays(
    client: TestClient,
) -> None:
    key = _idempotency_key()
    payload = {
        "full_name": "更新后的提交人",
        "email": "submitter-updated@example.com",
        "expected_user_version": 1,
    }
    response = client.patch(
        f"{settings.API_V1_STR}/users/me",
        headers={**_submitter_headers(client), "Idempotency-Key": key},
        json=payload,
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["email"] == "submitter-updated@example.com"
    assert result["version"] == 2

    replay = client.patch(
        f"{settings.API_V1_STR}/users/me",
        headers={"Authorization": response.request.headers["Authorization"], "Idempotency-Key": key},
        json=payload,
    )
    assert replay.status_code == 200
    assert replay.json() == result

    with Session(engine) as session:
        user = _user(session, "submitter-updated@example.com")
        assert user.version == 2
        audit = session.exec(
            select(AuditLog).where(
                AuditLog.entity_id == user.id,
                AuditLog.action == "USER_ROLES_CHANGED",
            )
        ).all()
        assert audit == []
        user_audit = session.exec(
            select(AuditLog).where(
                AuditLog.entity_id == user.id,
                AuditLog.entity_type == "USER",
            )
        ).one()
        assert user_audit.idempotency_key == key
        records = session.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.command_scope == "UPDATE_SELF"
            )
        ).all()
        assert len(records) == 1


def test_vs6_admin_manages_users_roles_and_last_admin(
    client: TestClient,
) -> None:
    admin_headers = _admin_headers(client)
    email = "managed-user@example.com"
    created = client.post(
        f"{settings.API_V1_STR}/users",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "email": email,
            "password": "managed-password",
            "full_name": "受管用户",
            "roles": ["SUBMITTER", "HANDLER"],
        },
    )
    assert created.status_code == 201, created.text
    created_payload = created.json()
    assert created_payload["version"] == 1
    assert set(created_payload["roles"]) == {"SUBMITTER", "HANDLER"}
    user_id = created_payload["id"]

    listed = client.get(
        f"{settings.API_V1_STR}/users",
        params={"role": "HANDLER"},
        headers=admin_headers,
    )
    assert listed.status_code == 200
    assert user_id in {item["id"] for item in listed.json()["items"]}

    detail = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=admin_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["email"] == email

    updated = client.patch(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"is_active": False, "expected_user_version": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["is_active"] is False

    roles = client.put(
        f"{settings.API_V1_STR}/users/{user_id}/roles",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"roles": ["SUBMITTER"], "expected_user_version": 2},
    )
    assert roles.status_code == 200
    assert roles.json()["roles"] == ["SUBMITTER"]
    assert roles.json()["version"] == 3

    forbidden = client.get(
        f"{settings.API_V1_STR}/users",
        headers=_submitter_headers(client),
    )
    assert forbidden.status_code == 403

    with Session(engine) as session:
        admin = _user(session, str(settings.FIRST_SUPERUSER))
        admin_id = admin.id
        admin_version = admin.version
    last_admin = client.patch(
        f"{settings.API_V1_STR}/users/{admin_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"is_active": False, "expected_user_version": admin_version},
    )
    assert last_admin.status_code == 409
    assert last_admin.json()["error"]["code"] == "LAST_ADMIN_REQUIRED"


def test_vs6_team_version_membership_and_inactive_candidates(
    client: TestClient,
) -> None:
    admin_headers = _admin_headers(client)
    created_team = client.post(
        f"{settings.API_V1_STR}/teams",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"name": "VS6 团队"},
    )
    assert created_team.status_code == 201, created_team.text
    team_payload = created_team.json()
    team_id = team_payload["id"]
    assert team_payload["version"] == 1

    handler = client.post(
        f"{settings.API_V1_STR}/users",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "email": "team-member@example.com",
            "password": "member-password",
            "roles": ["HANDLER"],
        },
    )
    assert handler.status_code == 201
    handler_id = handler.json()["id"]

    member = client.put(
        f"{settings.API_V1_STR}/teams/{team_id}/members/{handler_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"is_available": True, "expected_team_version": 1},
    )
    assert member.status_code == 200, member.text
    assert member.json()["team_version"] == 2

    unavailable = client.put(
        f"{settings.API_V1_STR}/teams/{team_id}/members/{handler_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"is_available": False, "expected_team_version": 2},
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["team_version"] == 3

    members = client.get(
        f"{settings.API_V1_STR}/teams/{team_id}/members",
        headers=_dispatcher_headers(client),
    )
    assert members.status_code == 200
    assert members.json()["items"][0]["user"]["id"] == handler_id

    ticket = _create_ticket(client, uuid.UUID(team_id))
    deactivated = client.patch(
        f"{settings.API_V1_STR}/teams/{team_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"is_active": False, "expected_version": 3},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["version"] == 4
    candidates = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch-candidates",
        headers=_dispatcher_headers(client),
    )
    assert candidates.status_code == 200
    assert candidates.json()["candidate_count"] == 0

    removed = client.delete(
        f"{settings.API_V1_STR}/teams/{team_id}/members/{handler_id}",
        params={"expected_team_version": 4},
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
    )
    assert removed.status_code == 200
    assert removed.json()["removed_user_id"] == handler_id
    assert removed.json()["team_version"] == 5


def test_vs6_removing_member_preserves_assignment_history(
    client: TestClient,
) -> None:
    admin_headers = _admin_headers(client)
    with Session(engine) as session:
        team = _team(session)
        team_id = team.id
        team_version = team.version
    handler = client.post(
        f"{settings.API_V1_STR}/users",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "email": "history-handler@example.com",
            "password": "history-password",
            "roles": ["HANDLER"],
        },
    )
    handler_id = handler.json()["id"]
    member = client.put(
        f"{settings.API_V1_STR}/teams/{team_id}/members/{handler_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"is_available": True, "expected_team_version": team_version},
    )
    assert member.status_code == 200
    ticket = _create_ticket(client, team_id)
    dispatched = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": handler_id,
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert dispatched.status_code == 201

    removed = client.delete(
        f"{settings.API_V1_STR}/teams/{team_id}/members/{handler_id}",
        params={"expected_team_version": 2},
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
    )
    assert removed.status_code == 200
    with Session(engine) as session:
        assert session.get(
            Assignment,
            uuid.UUID(dispatched.json()["assignment"]["id"]),
        ) is not None


def test_vs6_two_admins_cannot_concurrently_remove_each_other(
    client: TestClient,
) -> None:
    admin_headers = _admin_headers(client)
    created = client.post(
        f"{settings.API_V1_STR}/users",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "email": "second-admin@example.com",
            "password": "second-admin-password",
            "roles": ["ADMIN"],
        },
    )
    assert created.status_code == 201
    second_id = created.json()["id"]
    second_headers = _login(
        client,
        "second-admin@example.com",
        "second-admin-password",
    )
    with Session(engine) as session:
        first_id = str(_user(session, str(settings.FIRST_SUPERUSER)).id)

    def deactivate(headers: dict[str, str], target_id: str) -> int:
        with TestClient(app) as local_client:
            response = local_client.patch(
                f"{settings.API_V1_STR}/users/{target_id}",
                headers={**headers, "Idempotency-Key": _idempotency_key()},
                json={"is_active": False, "expected_user_version": 1},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(deactivate, admin_headers, second_id)
        second_future = executor.submit(deactivate, second_headers, first_id)
        statuses = [first_future.result(), second_future.result()]

    assert statuses.count(200) == 1
    assert all(status in (200, 403, 409) for status in statuses)
    with Session(engine) as session:
        active_admins = session.exec(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                User.is_active.is_(True),
                UserRole.role_code == "ADMIN",
            )
        ).all()
        assert len(active_admins) >= 1
