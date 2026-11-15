"""VS2 Ticket 创建、可见性、编辑与评论验收。"""

import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
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
    Comment,
    IdempotencyRecord,
    Team,
    Ticket,
    User,
    UserCreate,
)


@pytest.fixture()
def vs2_db(clean_db: Session) -> Generator[None]:
    """每例从空业务库重新种入 VS1 四角色和 Team。"""

    with Session(engine) as setup_session:
        seed_vs1_demo_data(setup_session)
    clean_db.expunge_all()
    yield
    clean_db.rollback()
    clean_db.expunge_all()


pytestmark = pytest.mark.usefixtures("vs2_db")


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _submitter_headers(client: TestClient) -> dict[str, str]:
    return _login(client, VS1_SUBMITTER_EMAIL, VS1_DEMO_PASSWORD)


def _dispatcher_headers(client: TestClient) -> dict[str, str]:
    return _login(client, VS1_DISPATCHER_EMAIL, VS1_DEMO_PASSWORD)


def _handler_headers(client: TestClient) -> dict[str, str]:
    return _login(client, VS1_HANDLER_EMAILS[0], VS1_DEMO_PASSWORD)


def _admin_headers(client: TestClient) -> dict[str, str]:
    return _login(
        client,
        str(settings.FIRST_SUPERUSER),
        settings.FIRST_SUPERUSER_PASSWORD,
    )


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def _team(session: Session) -> Team:
    team = session.exec(select(Team).where(Team.name == VS1_TEAM_NAME)).one()
    return team


def _user(session: Session, email: str) -> User:
    user = crud.get_user_by_email(session=session, email=email)
    assert user is not None
    return user


def _create_ticket_via_api(
    client: TestClient,
    *,
    headers: dict[str, str],
    key: str | None = None,
    title: str = "无法访问共享目录",
    description: str = "访问项目共享目录时持续返回权限错误。",
) -> dict[str, object]:
    with Session(engine) as session:
        team_id = _team(session).id
    response = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={**headers, "Idempotency-Key": key or _idempotency_key()},
        json={
            "team_id": str(team_id),
            "title": title,
            "description": description,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _insert_ticket(
    session: Session,
    *,
    submitter: User,
    title: str,
    created_at: datetime | None = None,
    status: str = "PENDING_ASSIGNMENT",
) -> Ticket:
    now = created_at or datetime.now(UTC)
    ticket = Ticket(
        team_id=_team(session).id,
        submitter_id=submitter.id,
        title=title,
        description=f"{title}的详细描述",
        status=status,
        created_at=now,
        updated_at=now,
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
    status: str = "REJECTED",
) -> Assignment:
    assignment = Assignment(
        ticket_id=ticket.id,
        handler_id=handler.id,
        assigned_by_id=assigned_by.id,
        status=status,
        dispatch_mode="MANUAL",
        strategy_code="MANUAL",
        strategy_version="v1",
        reason="测试历史派发" if status == "REJECTED" else None,
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def _create_user_with_roles(
    session: Session,
    *,
    email: str,
    roles: tuple[str, ...],
) -> User:
    user = crud.create_user(
        session=session,
        user_create=UserCreate(
            email=email,
            password=VS1_DEMO_PASSWORD,
            full_name="VS2 测试用户",
        ),
    )
    for role in roles:
        crud.ensure_user_role(session=session, user_id=user.id, role_code=role)
    return user


def test_vs2_create_sets_server_fields_audits_and_replays(
    client: TestClient,
) -> None:
    headers = _submitter_headers(client)
    key = _idempotency_key()

    created = _create_ticket_via_api(client, headers=headers, key=key)

    assert created["status"] == "PENDING_ASSIGNMENT"
    assert created["version"] == 1
    assert created["title"] == "无法访问共享目录"
    assert created["active_assignment"] is None
    assert created["allowed_actions"] == ["EDIT", "COMMENT"]

    with Session(engine) as session:
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        ticket = session.get(Ticket, uuid.UUID(str(created["id"])))
        assert ticket is not None
        assert ticket.submitter_id == submitter.id
        audit = session.exec(select(AuditLog)).one()
        assert audit.action == "TICKET_CREATED"
        assert audit.request_id is not None
        assert audit.detail == {
            "changed_fields": ["team_id", "title", "description", "status"]
        }
        assert "访问项目共享目录时" not in str(audit.detail)
        record = session.exec(select(IdempotencyRecord)).one()
        assert record.request_hash
        assert record.response_body == created

    replay = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={**headers, "Idempotency-Key": key},
        json={
            "team_id": created["team_id"],
            "title": "无法访问共享目录",
            "description": "访问项目共享目录时持续返回权限错误。",
        },
    )
    assert replay.status_code == 201
    assert replay.json() == created

    conflict = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={**headers, "Idempotency-Key": key},
        json={
            "team_id": created["team_id"],
            "title": "另一个标题",
            "description": "访问项目共享目录时持续返回权限错误。",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    with Session(engine) as session:
        assert len(session.exec(select(Ticket)).all()) == 1
        assert len(session.exec(select(AuditLog)).all()) == 1
        assert len(session.exec(select(IdempotencyRecord)).all()) == 1


def test_vs2_create_rejects_missing_key_unknown_fields_and_inactive_team(
    client: TestClient,
) -> None:
    headers = _submitter_headers(client)
    with Session(engine) as session:
        team_id = _team(session).id

    missing_key = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers=headers,
        json={"team_id": str(team_id), "title": "标题", "description": "描述"},
    )
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISSING"

    unknown = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={**headers, "Idempotency-Key": _idempotency_key()},
        json={
            "team_id": str(team_id),
            "title": "标题",
            "description": "描述",
            "submitter_id": str(uuid.uuid4()),
            "status": "CLOSED",
            "version": 99,
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "VALIDATION_ERROR"
    assert unknown.headers["X-Request-ID"] == unknown.json()["error"]["request_id"]

    with Session(engine) as session:
        inactive = Team(name="停用团队", is_active=False)
        session.add(inactive)
        session.commit()
        inactive_id = inactive.id
    inactive_response = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={**headers, "Idempotency-Key": _idempotency_key()},
        json={
            "team_id": str(inactive_id),
            "title": "标题",
            "description": "描述",
        },
    )
    assert inactive_response.status_code == 404
    assert inactive_response.json()["error"]["code"] == "TEAM_NOT_FOUND"


def test_vs2_visibility_is_role_scoped_and_uses_union(
    client: TestClient,
) -> None:
    submitter_headers = _submitter_headers(client)
    handler_headers = _handler_headers(client)
    dispatcher_headers = _dispatcher_headers(client)
    admin_headers = _admin_headers(client)

    own = _create_ticket_via_api(client, headers=submitter_headers, title="本人工单")
    with Session(engine) as session:
        other_submitter = _create_user_with_roles(
            session,
            email="other-submitter@example.com",
            roles=("SUBMITTER",),
        )
        handler = _user(session, VS1_HANDLER_EMAILS[0])
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        assigned_to_handler = _insert_ticket(
            session,
            submitter=other_submitter,
            title="历史派给处理人",
        )
        _insert_assignment(
            session,
            ticket=assigned_to_handler,
            handler=handler,
            assigned_by=dispatcher,
        )
        assigned_to_handler_id = assigned_to_handler.id
        hidden = _insert_ticket(
            session,
            submitter=other_submitter,
            title="其他人不可见",
        )
        hidden_id = hidden.id

    submitter_list = client.get(
        f"{settings.API_V1_STR}/tickets",
        headers=submitter_headers,
    )
    assert submitter_list.status_code == 200
    assert {item["id"] for item in submitter_list.json()["items"]} == {own["id"]}
    hidden_detail = client.get(
        f"{settings.API_V1_STR}/tickets/{hidden_id}",
        headers=submitter_headers,
    )
    assert hidden_detail.status_code == 404
    assert hidden_detail.json()["error"]["code"] == "TICKET_NOT_FOUND"

    handler_list = client.get(
        f"{settings.API_V1_STR}/tickets",
        headers=handler_headers,
    )
    assert {item["id"] for item in handler_list.json()["items"]} == {
        str(assigned_to_handler_id)
    }
    for headers, expected_count in (
        (dispatcher_headers, 3),
        (admin_headers, 3),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/tickets",
            headers=headers,
        )
        assert response.status_code == 200
        assert len(response.json()["items"]) == expected_count

    with Session(engine) as session:
        multirole = _create_user_with_roles(
            session,
            email="multi-role-vs2@example.com",
            roles=("SUBMITTER", "HANDLER"),
        )
        own_by_multirole = _insert_ticket(
            session,
            submitter=multirole,
            title="多角色本人",
        )
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        assigned_to_multirole = _insert_ticket(
            session,
            submitter=_user(session, "other-submitter@example.com"),
            title="多角色历史派发",
        )
        _insert_assignment(
            session,
            ticket=assigned_to_multirole,
            handler=multirole,
            assigned_by=dispatcher,
        )
        own_by_multirole_id = own_by_multirole.id
        assigned_to_multirole_id = assigned_to_multirole.id
    multirole_headers = _login(
        client,
        "multi-role-vs2@example.com",
        VS1_DEMO_PASSWORD,
    )
    union = client.get(
        f"{settings.API_V1_STR}/tickets",
        headers=multirole_headers,
    )
    assert {item["id"] for item in union.json()["items"]} == {
        str(own_by_multirole_id),
        str(assigned_to_multirole_id),
    }


def test_vs2_list_filters_sort_keyset_and_cursor_binding(
    client: TestClient,
) -> None:
    submitter_headers = _submitter_headers(client)
    dispatcher_headers = _dispatcher_headers(client)
    handler_headers = _handler_headers(client)
    base = datetime.now(UTC) - timedelta(days=3)

    with Session(engine) as session:
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        handler = _user(session, VS1_HANDLER_EMAILS[0])
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        tickets = [
            _insert_ticket(
                session,
                submitter=submitter,
                title=f"分页工单 {index}",
                created_at=base + timedelta(minutes=index),
            )
            for index in range(3)
        ]
        _insert_assignment(
            session,
            ticket=tickets[1],
            handler=handler,
            assigned_by=dispatcher,
        )
        submitter_id = submitter.id
        second_id = tickets[1].id

    first_page = client.get(
        f"{settings.API_V1_STR}/tickets",
        params={"sort": "created_at:asc", "limit": 2},
        headers=submitter_headers,
    )
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert len(first_payload["items"]) == 2
    assert first_payload["next_cursor"] is not None

    second_page = client.get(
        f"{settings.API_V1_STR}/tickets",
        params={
            "sort": "created_at:asc",
            "limit": 2,
            "cursor": first_payload["next_cursor"],
        },
        headers=submitter_headers,
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["next_cursor"] is None

    rebound_cursor = client.get(
        f"{settings.API_V1_STR}/tickets",
        params={
            "sort": "created_at:asc",
            "limit": 2,
            "status": "PENDING_ASSIGNMENT",
            "cursor": first_payload["next_cursor"],
        },
        headers=submitter_headers,
    )
    assert rebound_cursor.status_code == 422
    assert rebound_cursor.json()["error"]["code"] == "INVALID_CURSOR"

    invalid_sort = client.get(
        f"{settings.API_V1_STR}/tickets",
        params={"sort": "title:asc"},
        headers=submitter_headers,
    )
    assert invalid_sort.status_code == 422
    assert invalid_sort.json()["error"]["code"] == "INVALID_SORT"

    forbidden_filter = client.get(
        f"{settings.API_V1_STR}/tickets",
        params={"submitter_id": str(submitter_id)},
        headers=handler_headers,
    )
    assert forbidden_filter.status_code == 403
    assert forbidden_filter.json()["error"]["code"] == "ACTION_FORBIDDEN"

    filtered = client.get(
        f"{settings.API_V1_STR}/tickets",
        params={"submitter_id": str(submitter_id)},
        headers=dispatcher_headers,
    )
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 3

    assigned_to_me = client.get(
        f"{settings.API_V1_STR}/tickets",
        params={"assigned_to_me": "true"},
        headers=handler_headers,
    )
    assert assigned_to_me.status_code == 200
    assert [item["id"] for item in assigned_to_me.json()["items"]] == [
        str(second_id)
    ]


def test_vs2_update_permissions_versions_audit_and_idempotency(
    client: TestClient,
) -> None:
    submitter_headers = _submitter_headers(client)
    handler_headers = _handler_headers(client)
    admin_headers = _admin_headers(client)
    ticket = _create_ticket_via_api(client, headers=submitter_headers)
    ticket_id = ticket["id"]

    with Session(engine) as session:
        handler = _user(session, VS1_HANDLER_EMAILS[0])
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        assigned_ticket = session.get(Ticket, uuid.UUID(str(ticket_id)))
        assert assigned_ticket is not None
        _insert_assignment(
            session,
            ticket=assigned_ticket,
            handler=handler,
            assigned_by=dispatcher,
        )

    forbidden = client.patch(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={"title": "处理人不能改", "expected_version": 1},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "ACTION_FORBIDDEN"

    key = _idempotency_key()
    update_payload = {
        "title": "已更新标题",
        "description": "已更新描述",
        "expected_version": 1,
    }
    updated = client.patch(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers={**submitter_headers, "Idempotency-Key": key},
        json=update_payload,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["title"] == "已更新标题"

    replay = client.patch(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers={**submitter_headers, "Idempotency-Key": key},
        json=update_payload,
    )
    assert replay.status_code == 200
    assert replay.json() == updated.json()

    stale = client.patch(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"title": "旧版本覆盖", "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_VERSION"

    admin_update = client.patch(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers={**admin_headers, "Idempotency-Key": _idempotency_key()},
        json={"description": "管理员补充描述", "expected_version": 2},
    )
    assert admin_update.status_code == 200
    assert admin_update.json()["version"] == 3

    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket_id)))
        assert ticket_row is not None
        ticket_row.status = "ASSIGNED"
        session.add(ticket_row)
        session.commit()
    invalid_status = client.patch(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers={**submitter_headers, "Idempotency-Key": _idempotency_key()},
        json={"title": "状态不允许", "expected_version": 3},
    )
    assert invalid_status.status_code == 409
    assert invalid_status.json()["error"]["code"] == "INVALID_TRANSITION"

    with Session(engine) as session:
        updates = session.exec(
            select(AuditLog).where(AuditLog.action == "TICKET_UPDATED")
        ).all()
        assert len(updates) == 2
        assert updates[0].before_state == {
            "status": "PENDING_ASSIGNMENT",
            "version": 1,
        }
        assert updates[0].after_state == {
            "status": "PENDING_ASSIGNMENT",
            "version": 2,
        }


def test_vs2_comments_are_visible_incremental_and_idempotent(
    client: TestClient,
) -> None:
    submitter_headers = _submitter_headers(client)
    handler_headers = _handler_headers(client)
    ticket = _create_ticket_via_api(client, headers=submitter_headers)
    ticket_id = ticket["id"]

    with Session(engine) as session:
        handler = _user(session, VS1_HANDLER_EMAILS[0])
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        assigned_ticket = session.get(Ticket, uuid.UUID(str(ticket_id)))
        assert assigned_ticket is not None
        _insert_assignment(
            session,
            ticket=assigned_ticket,
            handler=handler,
            assigned_by=dispatcher,
        )

    first_key = _idempotency_key()
    first = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        headers={**handler_headers, "Idempotency-Key": first_key},
        json={"body": "  我先排查网络配置。  ", "expected_ticket_version": 1},
    )
    assert first.status_code == 201, first.text
    assert first.json()["body"] == "我先排查网络配置。"
    assert first.json()["author"]["email"] == VS1_HANDLER_EMAILS[0]

    replay = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        headers={**handler_headers, "Idempotency-Key": first_key},
        json={"body": "我先排查网络配置。", "expected_ticket_version": 1},
    )
    assert replay.status_code == 201
    assert replay.json() == first.json()

    detail = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers=submitter_headers,
    )
    assert detail.json()["version"] == 2

    second = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        headers={**submitter_headers, "Idempotency-Key": _idempotency_key()},
        json={"body": "已补充错误截图。", "expected_ticket_version": 2},
    )
    assert second.status_code == 201

    comments = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        params={"limit": 1},
        headers=submitter_headers,
    )
    assert comments.status_code == 200
    assert len(comments.json()["items"]) == 1
    assert comments.json()["next_cursor"] is not None
    comments_page_two = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        params={"limit": 1, "cursor": comments.json()["next_cursor"]},
        headers=submitter_headers,
    )
    assert [item["body"] for item in comments_page_two.json()["items"]] == [
        "已补充错误截图。"
    ]

    with Session(engine) as session:
        assert len(session.exec(select(Comment)).all()) == 2
        comments_audit = session.exec(
            select(AuditLog).where(AuditLog.action == "COMMENT_CREATED")
        ).all()
        assert len(comments_audit) == 2
        assert all("排查" not in str(item.detail) for item in comments_audit)
        records = session.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.command_scope == "CREATE_COMMENT"
            )
        ).all()
        assert len(records) == 2


def test_vs2_comment_hides_ticket_checks_version_and_rejects_closed(
    client: TestClient,
) -> None:
    submitter_headers = _submitter_headers(client)
    ticket = _create_ticket_via_api(client, headers=submitter_headers)
    ticket_id = uuid.UUID(str(ticket["id"]))

    with Session(engine) as session:
        _create_user_with_roles(
            session,
            email="hidden-commenter@example.com",
            roles=("SUBMITTER",),
        )
        ticket_row = session.get(Ticket, ticket_id)
        assert ticket_row is not None
        ticket_row.version = 2
        ticket_row.status = "CLOSED"
        session.add(ticket_row)
        session.commit()

    hidden_headers = _login(
        client,
        "hidden-commenter@example.com",
        VS1_DEMO_PASSWORD,
    )
    hidden = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        headers={**hidden_headers, "Idempotency-Key": _idempotency_key()},
        json={"body": "无权评论", "expected_ticket_version": 2},
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "TICKET_NOT_FOUND"

    stale = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        headers={**submitter_headers, "Idempotency-Key": _idempotency_key()},
        json={"body": "过期版本", "expected_ticket_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_VERSION"

    closed = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/comments",
        headers={**submitter_headers, "Idempotency-Key": _idempotency_key()},
        json={"body": "关闭后评论", "expected_ticket_version": 2},
    )
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "TICKET_CLOSED"

    detail = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket_id}",
        headers=submitter_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["allowed_actions"] == ["REOPEN"]


def test_vs2_same_idempotency_key_concurrency_creates_one_ticket(
    client: TestClient,
) -> None:
    headers = _submitter_headers(client)
    with Session(engine) as session:
        team_id = _team(session).id
    key = _idempotency_key()
    payload = {
        "team_id": str(team_id),
        "title": "并发幂等工单",
        "description": "两个请求使用同一幂等键。",
    }

    def submit() -> tuple[int, dict[str, object]]:
        with TestClient(client.app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/tickets",
                headers={**headers, "Idempotency-Key": key},
                json=payload,
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))

    assert {status_code for status_code, _body in results} == {201}
    assert len({body["id"] for _status, body in results}) == 1
    with Session(engine) as session:
        assert len(session.exec(select(Ticket)).all()) == 1
        assert len(session.exec(select(AuditLog)).all()) == 1
        assert len(session.exec(select(IdempotencyRecord)).all()) == 1


def test_vs2_openapi_exposes_only_stage_endpoints_and_strict_requests(
    client: TestClient,
) -> None:
    spec = client.get(f"{settings.API_V1_STR}/openapi.json").json()
    paths = {
        path
        for path in spec["paths"]
        if path.startswith(f"{settings.API_V1_STR}/tickets")
    }
    assert {
        f"{settings.API_V1_STR}/tickets",
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}",
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/comments",
    }.issubset(paths)
    assert set(spec["paths"][f"{settings.API_V1_STR}/tickets"]) == {"get", "post"}
    detail_path = spec["paths"][
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}"
    ]
    assert set(detail_path) == {"get", "patch"}
    create_schema = spec["components"]["schemas"]["TicketCreateRequest"]
    assert create_schema["additionalProperties"] is False
    assert set(create_schema["properties"]) == {
        "team_id",
        "title",
        "description",
    }


def test_vs2_unauthenticated_and_missing_ticket_return_contract_errors(
    client: TestClient,
) -> None:
    unauthenticated = client.get(f"{settings.API_V1_STR}/tickets")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "AUTH_REQUIRED"

    admin_headers = _admin_headers(client)
    missing = client.get(
        f"{settings.API_V1_STR}/tickets/{uuid.uuid4()}",
        headers=admin_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "TICKET_NOT_FOUND"
