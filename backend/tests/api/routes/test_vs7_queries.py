"""VS7 Ticket 时间线、Admin 审计与本人通知查询验收。"""

import json
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.core.seed import (
    VS1_DEMO_PASSWORD,
    VS1_DISPATCHER_EMAIL,
    VS1_HANDLER_EMAILS,
    VS1_SUBMITTER_EMAIL,
    VS1_TEAM_NAME,
    seed_vs1_demo_data,
)
from app.models import (
    Assignment,
    AuditLog,
    Notification,
    Team,
    Ticket,
    User,
    UserCreate,
)


@pytest.fixture()
def vs7_db(clean_db: Session) -> Generator[None]:
    """每例从空 PostgreSQL 业务库重建四角色和 Team。"""

    with Session(engine) as setup_session:
        seed_vs1_demo_data(setup_session)
    clean_db.expunge_all()
    yield
    clean_db.rollback()
    clean_db.expunge_all()


pytestmark = pytest.mark.usefixtures("vs7_db")


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _submitter_headers(client: TestClient) -> dict[str, str]:
    return _login(client, VS1_SUBMITTER_EMAIL, VS1_DEMO_PASSWORD)


def _dispatcher_headers(client: TestClient) -> dict[str, str]:
    return _login(client, VS1_DISPATCHER_EMAIL, VS1_DEMO_PASSWORD)


def _handler_headers(client: TestClient, index: int = 0) -> dict[str, str]:
    return _login(client, VS1_HANDLER_EMAILS[index], VS1_DEMO_PASSWORD)


def _admin_headers(client: TestClient) -> dict[str, str]:
    return _login(
        client,
        str(settings.FIRST_SUPERUSER),
        settings.FIRST_SUPERUSER_PASSWORD,
    )


def _user(session: Session, email: str) -> User:
    user = crud.get_user_by_email(session=session, email=email)
    assert user is not None
    return user


def _team(session: Session) -> Team:
    return session.exec(select(Team).where(Team.name == VS1_TEAM_NAME)).one()


def _insert_ticket(
    session: Session,
    *,
    submitter: User,
    title: str,
    created_at: datetime,
    status: str = "PENDING_ASSIGNMENT",
) -> Ticket:
    ticket = Ticket(
        team_id=_team(session).id,
        submitter_id=submitter.id,
        title=title,
        description=f"{title}的完整正文与敏感附件路径",
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def _insert_assignment(
    session: Session,
    *,
    ticket: Ticket,
    handler: User,
    assigned_by: User,
) -> Assignment:
    assignment = Assignment(
        ticket_id=ticket.id,
        handler_id=handler.id,
        assigned_by_id=assigned_by.id,
        status="REJECTED",
        dispatch_mode="MANUAL",
        strategy_code="MANUAL",
        strategy_version="v1",
        reason="测试历史派发",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def _insert_audit(
    session: Session,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    created_at: datetime,
    ticket_id: uuid.UUID | None = None,
    entity_key: dict[str, str] | None = None,
    outcome: str = "SUCCESS",
    detail: dict[str, object] | None = None,
) -> AuditLog:
    audit = AuditLog(
        actor_user_id=actor.id,
        actor_type="USER",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_key=entity_key,
        ticket_id=ticket_id,
        before_state={"status": "PENDING_ASSIGNMENT", "version": 1},
        after_state={"status": "ASSIGNED", "version": 2},
        outcome=outcome,
        request_id=uuid.uuid4(),
        detail=detail or {},
        created_at=created_at,
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return audit


def _create_submitter(
    session: Session,
    *,
    email: str,
) -> User:
    user = crud.create_user(
        session=session,
        user_create=UserCreate(
            email=email,
            password=VS1_DEMO_PASSWORD,
            full_name="VS7 隔离提交人",
        ),
    )
    crud.ensure_user_role(
        session=session,
        user_id=user.id,
        role_code="SUBMITTER",
    )
    session.commit()
    session.refresh(user)
    return user


def test_vs7_timeline_permissions_redaction_stable_order_and_pages(
    client: TestClient,
) -> None:
    headers = _submitter_headers(client)
    base = datetime.now(UTC) - timedelta(days=1)
    leaked_values = (
        "SECRET-COMMENT-BODY",
        "SECRET-PASSWORD",
        "SECRET-JWT",
        "FULL-TICKET-DESCRIPTION",
    )

    with Session(engine) as session:
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        handler = _user(session, VS1_HANDLER_EMAILS[0])
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        ticket = _insert_ticket(
            session,
            submitter=submitter,
            title="时间线脱敏工单",
            created_at=base,
            status="ASSIGNED",
        )
        assignment = _insert_assignment(
            session,
            ticket=ticket,
            handler=handler,
            assigned_by=dispatcher,
        )
        first = _insert_audit(
            session,
            actor=submitter,
            action="TICKET_CREATED",
            entity_type="TICKET",
            entity_id=ticket.id,
            ticket_id=ticket.id,
            created_at=base,
        )
        second = _insert_audit(
            session,
            actor=handler,
            action="COMMENT_CREATED",
            entity_type="TICKET",
            entity_id=ticket.id,
            ticket_id=ticket.id,
            created_at=base,
            detail={
                "changed_fields": ["comments"],
                "password": leaked_values[1],
                "jwt": leaked_values[2],
                "request_body": leaked_values[0],
                "description": leaked_values[3],
            },
        )
        third = _insert_audit(
            session,
            actor=dispatcher,
            action="ASSIGNMENT_CREATED",
            entity_type="ASSIGNMENT",
            entity_id=assignment.id,
            ticket_id=ticket.id,
            created_at=base,
            detail={
                "previous_status": "PENDING_ASSIGNMENT",
                "next_status": "ASSIGNED",
                "strategy_code": "MANUAL",
                "strategy_version": "v1",
                "selected_handler_id": str(handler.id),
            },
        )
        ticket_id = ticket.id
        assignment_id = assignment.id
        handler_id = handler.id
        expected_ids = [first.id, second.id, third.id]
        comment_event_id = second.id

    response = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == expected_ids
    assert [item["event_type"] for item in payload["items"]] == [
        "TICKET_CREATED",
        "COMMENT_CREATED",
        "ASSIGNMENT_CREATED",
    ]
    assignment_event = payload["items"][2]
    assert assignment_event["metadata"] == {
        "previous_status": "PENDING_ASSIGNMENT",
        "next_status": "ASSIGNED",
        "assignment_id": str(assignment_id),
        "handler_id": str(handler_id),
        "strategy_code": "MANUAL",
        "note": None,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert all(value not in serialized for value in leaked_values)
    assert "时间线脱敏工单" not in serialized

    first_page = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        params={"event_type": "COMMENT_CREATED", "limit": 1},
        headers=headers,
    )
    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()["items"]] == [comment_event_id]
    assert first_page.json()["next_cursor"] is None

    paged = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        params={"limit": 1},
        headers=headers,
    )
    assert paged.status_code == 200
    assert [item["id"] for item in paged.json()["items"]] == [first.id]
    assert paged.json()["next_cursor"] is not None
    page_two = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        params={"limit": 1, "cursor": paged.json()["next_cursor"]},
        headers=headers,
    )
    assert page_two.status_code == 200
    assert [item["id"] for item in page_two.json()["items"]] == [comment_event_id]

    rebound = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        params={
            "event_type": "ASSIGNMENT_CREATED",
            "cursor": paged.json()["next_cursor"],
        },
        headers=headers,
    )
    assert rebound.status_code == 422
    assert rebound.json()["error"]["code"] == "INVALID_CURSOR"

    invalid_cursor = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        params={"cursor": "not-a-valid-cursor"},
        headers=headers,
    )
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["error"]["code"] == "INVALID_CURSOR"

    invalid_sort = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        params={"sort": "created_at:desc"},
        headers=headers,
    )
    assert invalid_sort.status_code == 422
    assert invalid_sort.json()["error"]["code"] == "INVALID_SORT"


def test_vs7_timeline_reuses_ticket_visibility_for_all_roles(
    client: TestClient,
) -> None:
    base = datetime.now(UTC) - timedelta(hours=2)
    with Session(engine) as session:
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        hidden = _create_submitter(session, email="hidden-vs7@example.com")
        ticket = _insert_ticket(
            session,
            submitter=submitter,
            title="仅提交人可见",
            created_at=base,
        )
        _insert_audit(
            session,
            actor=submitter,
            action="TICKET_CREATED",
            entity_type="TICKET",
            entity_id=ticket.id,
            ticket_id=ticket.id,
            created_at=base,
        )
        ticket_id = ticket.id
        assert hidden.email != submitter.email

    hidden_headers = _login(client, "hidden-vs7@example.com", VS1_DEMO_PASSWORD)
    hidden_response = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
        headers=hidden_headers,
    )
    assert hidden_response.status_code == 404
    assert hidden_response.json()["error"]["code"] == "TICKET_NOT_FOUND"

    for headers in (
        _submitter_headers(client),
        _dispatcher_headers(client),
        _admin_headers(client),
    ):
        visible = client.get(
            f"{settings.API_V1_STR}/tickets/{ticket_id}/timeline",
            headers=headers,
        )
        assert visible.status_code == 200


def test_vs7_audit_admin_filters_entity_key_pages_and_redacts(
    client: TestClient,
) -> None:
    admin_headers = _admin_headers(client)
    non_admin = _dispatcher_headers(client)
    base = datetime.now(UTC) - timedelta(hours=3)
    user_key = str(uuid.uuid4())

    with Session(engine) as session:
        admin = _user(session, str(settings.FIRST_SUPERUSER))
        first = _insert_audit(
            session,
            actor=admin,
            action="USER_ROLES_CHANGED",
            entity_type="USER_ROLE",
            entity_id=uuid.uuid4(),
            entity_key={"user_id": user_key, "role_code": "HANDLER"},
            created_at=base,
            detail={
                "role_codes": ["HANDLER"],
                "password": "AUDIT-SECRET-PASSWORD",
                "jwt": "AUDIT-SECRET-JWT",
            },
        )
        second = _insert_audit(
            session,
            actor=admin,
            action="USER_ROLES_CHANGED",
            entity_type="USER_ROLE",
            entity_id=uuid.uuid4(),
            entity_key={"user_id": user_key, "role_code": "ADMIN"},
            created_at=base,
            detail={"role_codes": ["ADMIN"]},
        )
        third = _insert_audit(
            session,
            actor=admin,
            action="TEAM_MEMBER_CHANGED",
            entity_type="TEAM_MEMBERSHIP",
            entity_id=uuid.uuid4(),
            entity_key={"team_id": str(uuid.uuid4()), "user_id": user_key},
            created_at=base,
            detail={"changed_fields": ["is_available"]},
        )
        expected_desc = [third.id, second.id, first.id]

    forbidden = client.get(
        f"{settings.API_V1_STR}/admin/audit-logs",
        headers=non_admin,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "ROLE_REQUIRED"

    filtered = client.get(
        f"{settings.API_V1_STR}/admin/audit-logs",
        params={
            "entity_key": json.dumps(
                {"user_id": user_key, "role_code": "HANDLER"},
                separators=(",", ":"),
            )
        },
        headers=admin_headers,
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [first.id]
    assert filtered.json()["items"][0]["entity_key"] == {
        "user_id": user_key,
        "role_code": "HANDLER",
    }
    serialized = filtered.text
    assert "AUDIT-SECRET-PASSWORD" not in serialized
    assert "AUDIT-SECRET-JWT" not in serialized

    first_page = client.get(
        f"{settings.API_V1_STR}/admin/audit-logs",
        params={"entity_type": "USER_ROLE", "limit": 2},
        headers=admin_headers,
    )
    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()["items"]] == [
        second.id,
        first.id,
    ]
    assert first_page.json()["next_cursor"] is None

    paged = client.get(
        f"{settings.API_V1_STR}/admin/audit-logs",
        params={"limit": 1},
        headers=admin_headers,
    )
    assert paged.status_code == 200
    assert [item["id"] for item in paged.json()["items"]] == [expected_desc[0]]
    assert paged.json()["next_cursor"] is not None
    page_two = client.get(
        f"{settings.API_V1_STR}/admin/audit-logs",
        params={"limit": 1, "cursor": paged.json()["next_cursor"]},
        headers=admin_headers,
    )
    assert page_two.status_code == 200
    assert [item["id"] for item in page_two.json()["items"]] == [expected_desc[1]]

    rebound = client.get(
        f"{settings.API_V1_STR}/admin/audit-logs",
        params={
            "entity_type": "TEAM_MEMBERSHIP",
            "cursor": paged.json()["next_cursor"],
        },
        headers=admin_headers,
    )
    assert rebound.status_code == 422
    assert rebound.json()["error"]["code"] == "INVALID_CURSOR"

    for params, error_code in (
        ({"cursor": "broken"}, "INVALID_CURSOR"),
        ({"sort": "action:asc"}, "INVALID_SORT"),
        ({"entity_key": "[]"}, "VALIDATION_ERROR"),
    ):
        invalid = client.get(
            f"{settings.API_V1_STR}/admin/audit-logs",
            params=params,
            headers=admin_headers,
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == error_code

    assert client.delete(
        f"{settings.API_V1_STR}/admin/audit-logs",
        headers=admin_headers,
    ).status_code == 405
    assert client.patch(
        f"{settings.API_V1_STR}/admin/audit-logs/{first.id}",
        headers=admin_headers,
    ).status_code in {404, 405}


def test_vs7_notifications_are_recipient_only_filtered_and_hash_free(
    client: TestClient,
) -> None:
    handler_one = _handler_headers(client, 0)
    handler_two = _handler_headers(client, 1)
    base = datetime.now(UTC) - timedelta(hours=1)

    with Session(engine) as session:
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        first_handler = _user(session, VS1_HANDLER_EMAILS[0])
        second_handler = _user(session, VS1_HANDLER_EMAILS[1])
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        ticket = _insert_ticket(
            session,
            submitter=submitter,
            title="通知查询工单",
            created_at=base,
            status="ASSIGNED",
        )
        second_ticket = _insert_ticket(
            session,
            submitter=submitter,
            title="第二条通知工单",
            created_at=base + timedelta(minutes=2),
            status="ASSIGNED",
        )
        assignment = _insert_assignment(
            session,
            ticket=ticket,
            handler=first_handler,
            assigned_by=dispatcher,
        )
        second_assignment = _insert_assignment(
            session,
            ticket=second_ticket,
            handler=first_handler,
            assigned_by=dispatcher,
        )
        first = Notification(
            recipient_id=first_handler.id,
            ticket_id=ticket.id,
            assignment_id=assignment.id,
            notification_type="ASSIGNMENT_RECEIVED",
            payload={
                "title": "你收到一个新工单",
                "message": "工单“通知查询工单”已派发给你。",
            },
            created_at=base,
            read_at=datetime.now(UTC),
        )
        newest = Notification(
            recipient_id=first_handler.id,
            ticket_id=second_ticket.id,
            assignment_id=second_assignment.id,
            notification_type="ASSIGNMENT_RECEIVED",
            payload={
                "title": "你收到一个新工单",
                "message": "工单“第二条通知工单”已派发给你。",
            },
            created_at=base + timedelta(minutes=2),
        )
        second = Notification(
            recipient_id=second_handler.id,
            ticket_id=ticket.id,
            assignment_id=assignment.id,
            notification_type="ASSIGNMENT_RECEIVED",
            payload={
                "title": "你收到另一个新工单",
                "message": "另一条通知。",
            },
            created_at=base + timedelta(minutes=1),
        )
        session.add(first)
        session.add(newest)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.refresh(newest)
        session.refresh(second)
        first_id = first.id
        newest_id = newest.id
        second_id = second.id

    listed = client.get(
        f"{settings.API_V1_STR}/notifications",
        headers=handler_one,
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [
        str(newest_id),
        str(first_id),
    ]
    item = listed.json()["items"][1]
    assert set(item) == {
        "id",
        "notification_type",
        "ticket_id",
        "assignment_id",
        "title",
        "message",
        "created_at",
    }
    assert "read_at" not in item

    detail = client.get(
        f"{settings.API_V1_STR}/notifications/{first_id}",
        headers=handler_one,
    )
    assert detail.status_code == 200
    assert detail.json() == item

    hidden = client.get(
        f"{settings.API_V1_STR}/notifications/{second_id}",
        headers=handler_one,
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"

    paged = client.get(
        f"{settings.API_V1_STR}/notifications",
        params={"limit": 1},
        headers=handler_one,
    )
    assert paged.status_code == 200
    assert [entry["id"] for entry in paged.json()["items"]] == [str(newest_id)]
    assert paged.json()["next_cursor"] is not None
    page_two = client.get(
        f"{settings.API_V1_STR}/notifications",
        params={"limit": 1, "cursor": paged.json()["next_cursor"]},
        headers=handler_one,
    )
    assert page_two.status_code == 200
    assert [entry["id"] for entry in page_two.json()["items"]] == [str(first_id)]
    assert page_two.json()["next_cursor"] is None

    rebound = client.get(
        f"{settings.API_V1_STR}/notifications",
        params={
            "created_from": (base - timedelta(days=1)).isoformat(),
            "cursor": paged.json()["next_cursor"],
        },
        headers=handler_one,
    )
    assert rebound.status_code == 422
    assert rebound.json()["error"]["code"] == "INVALID_CURSOR"

    filtered = client.get(
        f"{settings.API_V1_STR}/notifications",
        params={
            "notification_type": "ASSIGNMENT_RECEIVED",
            "limit": 1,
        },
        headers=handler_two,
    )
    assert filtered.status_code == 200
    assert [entry["id"] for entry in filtered.json()["items"]] == [str(second_id)]
    assert filtered.json()["next_cursor"] is None

    invalid_cursor = client.get(
        f"{settings.API_V1_STR}/notifications",
        params={"cursor": "broken"},
        headers=handler_two,
    )
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["error"]["code"] == "INVALID_CURSOR"

    invalid_sort = client.get(
        f"{settings.API_V1_STR}/notifications",
        params={"sort": "title:asc"},
        headers=handler_two,
    )
    assert invalid_sort.status_code == 422
    assert invalid_sort.json()["error"]["code"] == "INVALID_SORT"

    openapi = client.get("/api/v1/openapi.json")
    assert openapi.status_code == 200
    assert "/api/v1/notifications/{notification_id}/read" not in openapi.json()[
        "paths"
    ]
