"""VS3 人工派发端到端主切片验收。"""

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
    VS1_HANDLER_EMAILS,
    VS1_SUBMITTER_EMAIL,
    VS1_TEAM_NAME,
    seed_vs1_demo_data,
)
from app.main import app
from app.models import (
    Assignment,
    AuditLog,
    IdempotencyRecord,
    Notification,
    Team,
    TeamMembership,
    Ticket,
    User,
    UserRole,
)
from app.services import assignments as assignment_service


@pytest.fixture()
def vs3_db(clean_db: Session) -> Generator[None]:
    """每例从空业务库种入 VS1 四角色、Team 和两名 Handler。"""

    with Session(engine) as setup_session:
        seed_vs1_demo_data(setup_session)
    clean_db.expunge_all()
    yield
    clean_db.rollback()
    clean_db.expunge_all()


pytestmark = pytest.mark.usefixtures("vs3_db")


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


def _handler_headers(client: TestClient, index: int = 0) -> dict[str, str]:
    return _login(client, VS1_HANDLER_EMAILS[index], VS1_DEMO_PASSWORD)


def _admin_headers(client: TestClient) -> dict[str, str]:
    return _login(
        client,
        str(settings.FIRST_SUPERUSER),
        settings.FIRST_SUPERUSER_PASSWORD,
    )


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def _team(session: Session) -> Team:
    return session.exec(select(Team).where(Team.name == VS1_TEAM_NAME)).one()


def _user(session: Session, email: str) -> User:
    user = crud.get_user_by_email(session=session, email=email)
    assert user is not None
    return user


def _create_ticket(client: TestClient) -> dict[str, object]:
    headers = _submitter_headers(client)
    with Session(engine) as session:
        team_id = _team(session).id
    response = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={**headers, "Idempotency-Key": _idempotency_key()},
        json={
            "team_id": str(team_id),
            "title": "人工派发主流程",
            "description": "用于验证候选、派发、接受、完成和关闭。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _insert_active_assignment_load(
    session: Session,
    *,
    handler: User,
    submitter: User,
    dispatcher: User,
) -> Ticket:
    ticket = Ticket(
        team_id=_team(session).id,
        submitter_id=submitter.id,
        title="已有负载工单",
        description="用于让处理人产生一条有效负载。",
        status="ASSIGNED",
    )
    session.add(ticket)
    session.flush()
    assignment = Assignment(
        ticket_id=ticket.id,
        handler_id=handler.id,
        assigned_by_id=dispatcher.id,
        status="ASSIGNED",
        dispatch_mode="MANUAL",
        strategy_code="MANUAL",
        strategy_version="v1",
    )
    membership = session.exec(
        select(TeamMembership).where(
            TeamMembership.team_id == ticket.team_id,
            TeamMembership.user_id == handler.id,
        )
    ).one()
    membership.last_assigned_at = ticket.updated_at
    session.add(assignment)
    session.add(membership)
    session.commit()
    session.refresh(ticket)
    return ticket


def _dispatch_ticket(
    client: TestClient,
    *,
    ticket_id: object,
    handler_id: uuid.UUID,
    expected_ticket_version: int = 1,
) -> dict[str, object]:
    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket_id}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(handler_id),
            "reason": None,
            "expected_ticket_version": expected_ticket_version,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_vs3_dispatch_candidates_rank_by_load_and_tie_breakers(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_one = _user(session, VS1_HANDLER_EMAILS[0])
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        _insert_active_assignment_load(
            session,
            handler=handler_one,
            submitter=submitter,
            dispatcher=dispatcher,
        )

    response = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch-candidates",
        headers=_dispatcher_headers(client),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket_id"] == ticket["id"]
    assert payload["candidate_count"] == 2
    assert [item["handler"]["email"] for item in payload["items"]] == [
        VS1_HANDLER_EMAILS[1],
        VS1_HANDLER_EMAILS[0],
    ]
    assert [item["open_ticket_count"] for item in payload["items"]] == [0, 1]
    assert [item["rank"] for item in payload["items"]] == [1, 2]


def test_vs3_manual_dispatch_creates_closed_loop_side_effects(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    headers = _dispatcher_headers(client)
    key = _idempotency_key()
    with Session(engine) as session:
        handler = _user(session, VS1_HANDLER_EMAILS[1])
        handler_id = handler.id

    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={**headers, "Idempotency-Key": key},
        json={
            "mode": "MANUAL",
            "handler_id": str(handler_id),
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "ASSIGNED"
    assert payload["ticket"]["version"] == 2
    assert payload["assignment"]["handler_id"] == str(handler_id)
    assert payload["assignment"]["status"] == "ASSIGNED"
    assert payload["assignment"]["version"] == 1
    assert payload["assignment"]["strategy_code"] == "MANUAL"
    assert payload["superseded_assignment_id"] is None
    assert payload["explanation"]["candidate_count"] == 2
    assert payload["explanation"]["selected_handler_id"] == str(handler_id)

    replay = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={**headers, "Idempotency-Key": key},
        json={
            "mode": "MANUAL",
            "handler_id": str(handler_id),
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert replay.status_code == 201
    assert replay.json() == payload

    with Session(engine) as session:
        assignments = session.exec(select(Assignment)).all()
        assert len(assignments) == 1
        notifications = session.exec(select(Notification)).all()
        assert len(notifications) == 1
        assert notifications[0].recipient_id == handler_id
        audits = session.exec(
            select(AuditLog).where(AuditLog.action == "ASSIGNMENT_CREATED")
        ).all()
        assert len(audits) == 1
        records = session.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.command_scope == "DISPATCH_TICKET"
            )
        ).all()
        assert len(records) == 1
        membership = session.exec(
            select(TeamMembership).where(
                TeamMembership.user_id == handler_id,
            )
        ).one()
        assert membership.last_assigned_at is not None


def test_vs3_assignment_history_and_active_assignment_are_visible(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    submitter_headers = _submitter_headers(client)

    empty_history = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/assignments",
        headers=submitter_headers,
    )
    assert empty_history.status_code == 200
    assert empty_history.json() == {"items": [], "next_cursor": None}

    empty_active = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/assignment",
        headers=submitter_headers,
    )
    assert empty_active.status_code == 200
    assert empty_active.json() == {
        "ticket_id": ticket["id"],
        "assignment": None,
    }

    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch_ticket(
        client,
        ticket_id=ticket["id"],
        handler_id=handler_id,
    )

    history = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/assignments",
        headers=submitter_headers,
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [
        dispatched["assignment"]["id"]
    ]

    active = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/assignment",
        headers=submitter_headers,
    )
    assert active.status_code == 200
    assert active.json()["assignment"]["id"] == dispatched["assignment"]["id"]
    assert active.json()["assignment"]["status"] == "ASSIGNED"


def test_vs3_current_handler_accepts_assignment(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch_ticket(
        client,
        ticket_id=ticket["id"],
        handler_id=handler_id,
    )
    key = _idempotency_key()
    body = {
        "expected_ticket_version": 2,
        "expected_assignment_version": 1,
    }

    response = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/accept"
        ),
        headers={**_handler_headers(client), "Idempotency-Key": key},
        json=body,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "IN_PROGRESS"
    assert payload["ticket"]["version"] == 3
    assert payload["changed_assignment"]["status"] == "ACCEPTED"
    assert payload["changed_assignment"]["version"] == 2
    assert payload["changed_assignment"]["responded_at"] is not None

    replay = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/accept"
        ),
        headers={**_handler_headers(client), "Idempotency-Key": key},
        json=body,
    )
    assert replay.status_code == 200
    assert replay.json() == payload

    with Session(engine) as session:
        assignment = session.get(
            Assignment,
            uuid.UUID(str(dispatched["assignment"]["id"])),
        )
        assert assignment is not None
        assert assignment.status == "ACCEPTED"
        audits = session.exec(
            select(AuditLog).where(AuditLog.action == "ASSIGNMENT_ACCEPTED")
        ).all()
        assert len(audits) == 1


def test_vs3_current_handler_completes_accepted_assignment(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    handler_headers = _handler_headers(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch_ticket(
        client,
        ticket_id=ticket["id"],
        handler_id=handler_id,
    )
    accepted = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/accept"
        ),
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert accepted.status_code == 200, accepted.text

    key = _idempotency_key()
    body = {
        "completion_note": "已恢复网络配置并验证共享目录访问。",
        "expected_ticket_version": 3,
        "expected_assignment_version": 2,
    }
    response = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/complete"
        ),
        headers={**handler_headers, "Idempotency-Key": key},
        json=body,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "PENDING_CONFIRMATION"
    assert payload["ticket"]["version"] == 4
    assert payload["changed_assignment"]["status"] == "COMPLETED"
    assert payload["changed_assignment"]["version"] == 3
    assert payload["changed_assignment"]["completion_note"] == body["completion_note"]
    assert payload["changed_assignment"]["finished_at"] is not None

    replay = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/complete"
        ),
        headers={**handler_headers, "Idempotency-Key": key},
        json=body,
    )
    assert replay.status_code == 200
    assert replay.json() == payload

    with Session(engine) as session:
        audits = session.exec(
            select(AuditLog).where(AuditLog.action == "ASSIGNMENT_COMPLETED")
        ).all()
        assert len(audits) == 1


def test_vs3_submitter_closes_completed_ticket(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    submitter_headers = _submitter_headers(client)
    handler_headers = _handler_headers(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch_ticket(
        client,
        ticket_id=ticket["id"],
        handler_id=handler_id,
    )
    accepted = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/accept"
        ),
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert accepted.status_code == 200
    completed = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/complete"
        ),
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "completion_note": "共享目录已恢复。",
            "expected_ticket_version": 3,
            "expected_assignment_version": 2,
        },
    )
    assert completed.status_code == 200

    key = _idempotency_key()
    body = {
        "resolution_note": "问题已解决，确认关闭。",
        "expected_ticket_version": 4,
    }
    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/close",
        headers={**submitter_headers, "Idempotency-Key": key},
        json=body,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "CLOSED"
    assert payload["ticket"]["version"] == 5
    assert payload["changed_assignment"] is None
    assert payload["superseded_assignment_id"] is None

    replay = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/close",
        headers={**submitter_headers, "Idempotency-Key": key},
        json=body,
    )
    assert replay.status_code == 200
    assert replay.json() == payload

    with Session(engine) as session:
        audits = session.exec(
            select(AuditLog).where(AuditLog.action == "TICKET_CLOSED")
        ).all()
        assert len(audits) == 1


def test_vs3_full_manual_flow_reaches_closed_state(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    dispatcher_headers = _dispatcher_headers(client)
    submitter_headers = _submitter_headers(client)

    candidates = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch-candidates",
        headers=dispatcher_headers,
    )
    assert candidates.status_code == 200
    selected = candidates.json()["items"][0]
    handler_headers = _login(
        client,
        selected["handler"]["email"],
        VS1_DEMO_PASSWORD,
    )
    dispatched = _dispatch_ticket(
        client,
        ticket_id=ticket["id"],
        handler_id=uuid.UUID(selected["handler_id"]),
    )

    assigned_detail = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}",
        headers=handler_headers,
    )
    assert assigned_detail.json()["status"] == "ASSIGNED"
    assert assigned_detail.json()["allowed_actions"] == [
        "COMMENT",
        "ACCEPT",
        "REJECT",
    ]

    accepted = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/accept"
        ),
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert accepted.status_code == 200

    completed = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/complete"
        ),
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "completion_note": "主流程处理完成。",
            "expected_ticket_version": 3,
            "expected_assignment_version": 2,
        },
    )
    assert completed.status_code == 200

    closed = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/close",
        headers={**submitter_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "resolution_note": "验收通过。",
            "expected_ticket_version": 4,
        },
    )
    assert closed.status_code == 200
    assert closed.json()["ticket"]["status"] == "CLOSED"

    final_detail = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}",
        headers=submitter_headers,
    )
    assert final_detail.json()["status"] == "CLOSED"
    assert final_detail.json()["active_assignment"] is None
    assert final_detail.json()["allowed_actions"] == ["REOPEN"]


def test_vs3_dispatch_rejects_role_ineligible_stale_and_conflicting_requests(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
        dispatcher_id = _user(session, VS1_DISPATCHER_EMAIL).id

    forbidden_candidates = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch-candidates",
        headers=_submitter_headers(client),
    )
    assert forbidden_candidates.status_code == 403

    ineligible = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(dispatcher_id),
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert ineligible.status_code == 409
    assert ineligible.json()["error"]["code"] == "HANDLER_NOT_ELIGIBLE"

    stale = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(handler_id),
            "reason": None,
            "expected_ticket_version": 2,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_VERSION"

    first_key = _idempotency_key()
    dispatched = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": first_key,
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(handler_id),
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert dispatched.status_code == 201

    conflict = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": first_key,
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(handler_id),
            "reason": "不同载荷",
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_vs3_notification_failure_rolls_back_dispatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id

    class BrokenNotification:
        def __init__(self, **_kwargs: object) -> None:
            raise RuntimeError("injected notification failure")

    monkeypatch.setattr(assignment_service, "Notification", BrokenNotification)
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = failing_client.post(
            f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
            headers={
                **_dispatcher_headers(failing_client),
                "Idempotency-Key": _idempotency_key(),
            },
            json={
                "mode": "MANUAL",
                "handler_id": str(handler_id),
                "reason": None,
                "expected_ticket_version": 1,
                "expected_assignment_id": None,
                "expected_assignment_version": None,
            },
        )
    assert response.status_code == 500

    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        assert ticket_row is not None
        assert ticket_row.status == "PENDING_ASSIGNMENT"
        assert ticket_row.version == 1
        assert session.exec(select(Assignment)).all() == []
        assert (
            session.exec(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.command_scope == "DISPATCH_TICKET"
                )
            ).all()
            == []
        )


def test_vs3_candidates_exclude_inactive_unavailable_and_submitter(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_one = _user(session, VS1_HANDLER_EMAILS[0])
        handler_two = _user(session, VS1_HANDLER_EMAILS[1])
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        team = _team(session)

        handler_one_membership = session.exec(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == handler_one.id,
            )
        ).one()
        handler_one_membership.is_available = False
        handler_two.is_active = False
        session.add(handler_one_membership)
        session.add(handler_two)
        session.add(UserRole(user_id=submitter.id, role_code="HANDLER"))
        session.add(TeamMembership(team_id=team.id, user_id=submitter.id))
        session.commit()

    candidates = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch-candidates",
        headers=_dispatcher_headers(client),
    )
    assert candidates.status_code == 200
    assert candidates.json()["items"] == []
    assert candidates.json()["candidate_count"] == 0


def test_vs3_assignment_actions_enforce_identity_and_visibility(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch_ticket(
        client,
        ticket_id=ticket["id"],
        handler_id=handler_id,
    )

    other_handler = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/accept"
        ),
        headers={
            **_handler_headers(client, 1),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert other_handler.status_code == 404
    assert other_handler.json()["error"]["code"] == "ASSIGNMENT_NOT_FOUND"

    visible_non_assignee = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/accept"
        ),
        headers={
            **_submitter_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert visible_non_assignee.status_code == 403
    assert visible_non_assignee.json()["error"]["code"] == "NOT_CURRENT_ASSIGNEE"

    premature_complete = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/complete"
        ),
        headers={
            **_handler_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "completion_note": "尚未接受便完成。",
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert premature_complete.status_code == 409
    assert premature_complete.json()["error"]["code"] == "INVALID_TRANSITION"


def test_vs3_same_idempotency_key_concurrent_dispatch_is_single_effect(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    dispatcher_headers = _dispatcher_headers(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    key = _idempotency_key()
    payload = {
        "mode": "MANUAL",
        "handler_id": str(handler_id),
        "reason": None,
        "expected_ticket_version": 1,
        "expected_assignment_id": None,
        "expected_assignment_version": None,
    }

    def dispatch() -> tuple[int, dict[str, object]]:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
                headers={**dispatcher_headers, "Idempotency-Key": key},
                json=payload,
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: dispatch(), range(2)))

    assert {status_code for status_code, _body in results} == {201}
    assert len({body["assignment"]["id"] for _status, body in results}) == 1
    with Session(engine) as session:
        assert len(session.exec(select(Assignment)).all()) == 1
        assert len(session.exec(select(Notification)).all()) == 1
        dispatch_audits = session.exec(
            select(AuditLog).where(AuditLog.action == "ASSIGNMENT_CREATED")
        ).all()
        assert len(dispatch_audits) == 1


def test_vs3_openapi_exposes_manual_closed_loop_only(
    client: TestClient,
) -> None:
    spec = client.get(f"{settings.API_V1_STR}/openapi.json").json()
    new_paths = {
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/assignments",
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/assignment",
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/dispatch-candidates",
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/dispatch",
        f"{settings.API_V1_STR}/assignments/{{assignment_id}}/accept",
        f"{settings.API_V1_STR}/assignments/{{assignment_id}}/complete",
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/actions/close",
    }
    assert new_paths.issubset(spec["paths"])
    manual_schema = spec["components"]["schemas"]["ManualDispatchRequest"]
    assert manual_schema["additionalProperties"] is False
    assert manual_schema["properties"]["mode"]["const"] == "MANUAL"
