"""VS5 自动派发、负载公平性和并发验收。"""

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
    Notification,
    Team,
    TeamMembership,
    Ticket,
    User,
)


@pytest.fixture()
def vs5_db(clean_db: Session) -> Generator[None]:
    with Session(engine) as setup_session:
        seed_vs1_demo_data(setup_session)
    clean_db.expunge_all()
    yield
    clean_db.rollback()
    clean_db.expunge_all()


pytestmark = pytest.mark.usefixtures("vs5_db")


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


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def _team(session: Session) -> Team:
    return session.exec(select(Team).where(Team.name == VS1_TEAM_NAME)).one()


def _user(session: Session, email: str) -> User:
    user = crud.get_user_by_email(session=session, email=email)
    assert user is not None
    return user


def _create_ticket(client: TestClient, title: str = "自动派发工单") -> dict[str, object]:
    with Session(engine) as session:
        team_id = _team(session).id
    response = client.post(
        f"{settings.API_V1_STR}/tickets",
        headers={
            **_submitter_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "team_id": str(team_id),
            "title": title,
            "description": "用于验证最低负载自动派发。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _insert_active_load(
    session: Session,
    *,
    handler: User,
    submitter: User,
    dispatcher: User,
) -> Ticket:
    ticket = Ticket(
        team_id=_team(session).id,
        submitter_id=submitter.id,
        title="已有负载",
        description="用于制造处理人初始负载。",
        status="ASSIGNED",
    )
    session.add(ticket)
    session.flush()
    session.add(
        Assignment(
            ticket_id=ticket.id,
            handler_id=handler.id,
            assigned_by_id=dispatcher.id,
            status="ASSIGNED",
            dispatch_mode="MANUAL",
            strategy_code="MANUAL",
            strategy_version="v1",
        )
    )
    membership = session.exec(
        select(TeamMembership).where(
            TeamMembership.team_id == ticket.team_id,
            TeamMembership.user_id == handler.id,
        )
    ).one()
    membership.last_assigned_at = ticket.updated_at
    session.add(membership)
    session.commit()
    session.refresh(ticket)
    return ticket


def test_vs5_auto_dispatch_selects_least_loaded_handler(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_one = _user(session, VS1_HANDLER_EMAILS[0])
        handler_two = _user(session, VS1_HANDLER_EMAILS[1])
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        _insert_active_load(
            session,
            handler=handler_one,
            submitter=submitter,
            dispatcher=dispatcher,
        )
        expected_handler_id = handler_two.id

    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "AUTO",
            "strategy": "LEAST_OPEN_TICKET",
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
    assert payload["assignment"]["handler_id"] == str(expected_handler_id)
    assert payload["assignment"]["dispatch_mode"] == "AUTO"
    assert payload["assignment"]["strategy_code"] == "LEAST_OPEN_TICKET"
    assert payload["assignment"]["strategy_version"] == "v1"
    assert payload["explanation"]["selected_handler_id"] == str(expected_handler_id)
    assert payload["explanation"]["selected_open_ticket_count"] == 0

    with Session(engine) as session:
        assignment = session.get(
            Assignment,
            uuid.UUID(str(payload["assignment"]["id"])),
        )
        assert assignment is not None
        assert assignment.dispatch_mode == "AUTO"
        notification = session.exec(
            select(Notification).where(
                Notification.assignment_id == assignment.id
            )
        ).one()
        assert notification.recipient_id == expected_handler_id
        audit = session.exec(
            select(AuditLog).where(AuditLog.entity_id == assignment.id)
        ).one()
        assert audit.action == "ASSIGNMENT_CREATED"
        assert audit.detail["strategy_code"] == "LEAST_OPEN_TICKET"


def test_vs5_auto_dispatch_without_candidates_keeps_business_state(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client, title="无候选自动派发")
    with Session(engine) as session:
        team_id = _team(session).id
        memberships = session.exec(
            select(TeamMembership).where(TeamMembership.team_id == team_id)
        ).all()
        for membership in memberships:
            membership.is_available = False
            session.add(membership)
        session.commit()

    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "AUTO",
            "strategy": "LEAST_OPEN_TICKET",
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_ELIGIBLE_HANDLER"

    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        assert ticket_row is not None
        assert ticket_row.status == "PENDING_ASSIGNMENT"
        assert ticket_row.version == 1
        assert (
            session.exec(
                select(Assignment).where(
                    Assignment.ticket_id == uuid.UUID(str(ticket["id"]))
                )
            ).all()
            == []
        )
        assert (
            session.exec(
                select(Notification).where(
                    Notification.ticket_id == uuid.UUID(str(ticket["id"]))
                )
            ).all()
            == []
        )
        failed_audit = session.exec(
            select(AuditLog).where(
                AuditLog.ticket_id == uuid.UUID(str(ticket["id"])),
                AuditLog.action == "AUTO_ASSIGN_FAILED",
            )
        ).one()
        assert failed_audit.outcome == "FAILED"
        assert failed_audit.error_code == "NO_ELIGIBLE_HANDLER"


def test_vs5_least_open_ticket_balances_preexisting_load(
    client: TestClient,
) -> None:
    with Session(engine) as session:
        handler_one = _user(session, VS1_HANDLER_EMAILS[0])
        handler_two = _user(session, VS1_HANDLER_EMAILS[1])
        submitter = _user(session, VS1_SUBMITTER_EMAIL)
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        for _ in range(2):
            _insert_active_load(
                session,
                handler=handler_one,
                submitter=submitter,
                dispatcher=dispatcher,
            )
        handler_one_id = handler_one.id
        handler_two_id = handler_two.id

    tickets = [
        _create_ticket(client, title=f"公平性工单 {index}")
        for index in range(4)
    ]
    selected_handlers: list[uuid.UUID] = []
    for ticket in tickets:
        response = client.post(
            f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
            headers={
                **_dispatcher_headers(client),
                "Idempotency-Key": _idempotency_key(),
            },
            json={
                "mode": "AUTO",
                "strategy": "LEAST_OPEN_TICKET",
                "reason": None,
                "expected_ticket_version": 1,
                "expected_assignment_id": None,
                "expected_assignment_version": None,
            },
        )
        assert response.status_code == 201, response.text
        selected_handlers.append(
            uuid.UUID(response.json()["assignment"]["handler_id"])
        )

    with Session(engine) as session:
        active_rows = session.exec(
            select(Assignment).where(
                Assignment.status.in_(("ASSIGNED", "ACCEPTED"))
            )
        ).all()
        counts = {
            handler_one_id: sum(
                item.handler_id == handler_one_id for item in active_rows
            ),
            handler_two_id: sum(
                item.handler_id == handler_two_id for item in active_rows
            ),
        }

    assert counts == {handler_one_id: 3, handler_two_id: 3}
    assert selected_handlers.count(handler_one_id) == 1
    assert selected_handlers.count(handler_two_id) == 3


def test_vs5_same_team_concurrent_auto_dispatch_recalculates_load(
    client: TestClient,
) -> None:
    first_ticket = _create_ticket(client, title="同 Team 并发 A")
    second_ticket = _create_ticket(client, title="同 Team 并发 B")
    dispatcher_headers = _dispatcher_headers(client)
    with Session(engine) as session:
        handler_ids = {
            _user(session, email).id for email in VS1_HANDLER_EMAILS
        }

    def dispatch(ticket_id: object) -> tuple[int, str | None]:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/tickets/{ticket_id}/dispatch",
                headers={
                    **dispatcher_headers,
                    "Idempotency-Key": _idempotency_key(),
                },
                json={
                    "mode": "AUTO",
                    "strategy": "LEAST_OPEN_TICKET",
                    "reason": None,
                    "expected_ticket_version": 1,
                    "expected_assignment_id": None,
                    "expected_assignment_version": None,
                },
            )
            return (
                response.status_code,
                response.json().get("assignment", {}).get("handler_id"),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(dispatch, first_ticket["id"])
        second_future = executor.submit(dispatch, second_ticket["id"])
        results = [first_future.result(), second_future.result()]

    assert {status_code for status_code, _handler in results} == {201}
    assert {
        handler_id for _status, handler_id in results
    } == {str(handler_id) for handler_id in handler_ids}


def test_vs5_fifty_idempotency_keys_produce_one_active_assignment(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client, title="50 请求自动派发")
    dispatcher_headers = _dispatcher_headers(client)

    def dispatch(_index: int) -> int:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
                headers={
                    **dispatcher_headers,
                    "Idempotency-Key": _idempotency_key(),
                },
                json={
                    "mode": "AUTO",
                    "strategy": "LEAST_OPEN_TICKET",
                    "reason": None,
                    "expected_ticket_version": 1,
                    "expected_assignment_id": None,
                    "expected_assignment_version": None,
                },
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        statuses = list(executor.map(dispatch, range(50)))

    assert statuses.count(201) == 1
    assert statuses.count(409) == 49
    with Session(engine) as session:
        active = session.exec(
            select(Assignment).where(
                Assignment.ticket_id == uuid.UUID(str(ticket["id"])),
                Assignment.status.in_(("ASSIGNED", "ACCEPTED")),
            )
        ).all()
        assert len(active) == 1
        notifications = session.exec(
            select(Notification).where(
                Notification.ticket_id == uuid.UUID(str(ticket["id"]))
            )
        ).all()
        assert len(notifications) == 1


def test_vs5_auto_redispatch_supersedes_current_assignment(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client, title="自动重新派发")
    dispatcher_headers = _dispatcher_headers(client)

    first = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **dispatcher_headers,
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "AUTO",
            "strategy": "LEAST_OPEN_TICKET",
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert first.status_code == 201, first.text
    first_assignment = first.json()["assignment"]

    second = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **dispatcher_headers,
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "AUTO",
            "strategy": "LEAST_OPEN_TICKET",
            "reason": "按最新负载重新分配。",
            "expected_ticket_version": 2,
            "expected_assignment_id": first_assignment["id"],
            "expected_assignment_version": 1,
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["superseded_assignment_id"] == first_assignment["id"]
    assert second.json()["assignment"]["handler_id"] != first_assignment["handler_id"]

    with Session(engine) as session:
        old = session.get(
            Assignment,
            uuid.UUID(str(first_assignment["id"])),
        )
        assert old is not None
        assert old.status == "SUPERSEDED"
        assert old.reason == "按最新负载重新分配。"


def test_vs5_auto_redispatch_to_same_handler_is_duplicate(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client, title="自动重复派发")
    dispatcher_headers = _dispatcher_headers(client)

    first = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **dispatcher_headers,
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "AUTO",
            "strategy": "LEAST_OPEN_TICKET",
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert first.status_code == 201
    assigned_handler_id = uuid.UUID(first.json()["assignment"]["handler_id"])
    with Session(engine) as session:
        other_membership = session.exec(
            select(TeamMembership).where(
                TeamMembership.team_id == _team(session).id,
                TeamMembership.user_id != assigned_handler_id,
            )
        ).one()
        other_membership.is_available = False
        session.add(other_membership)
        session.commit()

    duplicate = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **dispatcher_headers,
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "AUTO",
            "strategy": "LEAST_OPEN_TICKET",
            "reason": None,
            "expected_ticket_version": 2,
            "expected_assignment_id": first.json()["assignment"]["id"],
            "expected_assignment_version": 1,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_ASSIGNMENT"


def test_vs5_dispatch_discriminator_rejects_mixed_payloads(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client, title="判别联合校验")
    dispatcher_headers = _dispatcher_headers(client)

    manual_with_strategy = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **dispatcher_headers,
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(uuid.uuid4()),
            "strategy": "LEAST_OPEN_TICKET",
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert manual_with_strategy.status_code == 422

    auto_with_handler = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **dispatcher_headers,
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "AUTO",
            "strategy": "LEAST_OPEN_TICKET",
            "handler_id": str(uuid.uuid4()),
            "reason": None,
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert auto_with_handler.status_code == 422


def test_vs5_openapi_exposes_auto_strategy_schema(
    client: TestClient,
) -> None:
    spec = client.get(f"{settings.API_V1_STR}/openapi.json").json()
    auto_schema = spec["components"]["schemas"]["AutoDispatchRequest"]
    assert auto_schema["additionalProperties"] is False
    assert auto_schema["properties"]["mode"]["const"] == "AUTO"
    assert auto_schema["properties"]["strategy"]["const"] == "LEAST_OPEN_TICKET"
    dispatch_request = spec["paths"][
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/dispatch"
    ]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert len(dispatch_request["oneOf"]) == 2
    assert dispatch_request["discriminator"]["propertyName"] == "mode"
