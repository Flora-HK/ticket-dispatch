"""VS4 拒绝、重派、重开与并发保护验收。"""

import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

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
    Comment,
    Notification,
    Team,
    Ticket,
    User,
)
from app.services import assignments as assignment_service


@pytest.fixture()
def vs4_db(clean_db: Session) -> Generator[None]:
    with Session(engine) as setup_session:
        seed_vs1_demo_data(setup_session)
    clean_db.expunge_all()
    yield
    clean_db.rollback()
    clean_db.expunge_all()


pytestmark = pytest.mark.usefixtures("vs4_db")


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


def _idempotency_key() -> str:
    return str(uuid.uuid4())


def _team(session: Session) -> Team:
    return session.exec(select(Team).where(Team.name == VS1_TEAM_NAME)).one()


def _user(session: Session, email: str) -> User:
    user = crud.get_user_by_email(session=session, email=email)
    assert user is not None
    return user


def _create_ticket(client: TestClient) -> dict[str, object]:
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
            "title": "VS4 异常流转",
            "description": "验证拒绝、重派、重开与并发。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _dispatch(
    client: TestClient,
    *,
    ticket_id: object,
    handler_id: uuid.UUID,
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
            "expected_ticket_version": 1,
            "expected_assignment_id": None,
            "expected_assignment_version": None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_vs4_current_handler_rejects_assignment(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch(client, ticket_id=ticket["id"], handler_id=handler_id)

    response = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/reject"
        ),
        headers={
            **_handler_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "reason": "当前值班人员不具备所需权限。",
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "PENDING_ASSIGNMENT"
    assert payload["ticket"]["version"] == 3
    assert payload["changed_assignment"]["status"] == "REJECTED"
    assert payload["changed_assignment"]["version"] == 2
    assert payload["changed_assignment"]["reason"] == "当前值班人员不具备所需权限。"

    with Session(engine) as session:
        audits = session.exec(
            select(AuditLog).where(AuditLog.action == "ASSIGNMENT_REJECTED")
        ).all()
        assert len(audits) == 1
        active = session.exec(
            select(Assignment).where(
                Assignment.ticket_id == uuid.UUID(str(ticket["id"])),
                Assignment.status.in_(("ASSIGNED", "ACCEPTED")),
            )
        ).all()
        assert active == []


def test_vs4_redispatch_supersedes_old_assignment_and_notifies_new_handler(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        first_handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
        second_handler_id = _user(session, VS1_HANDLER_EMAILS[1]).id
    first = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=first_handler_id,
    )

    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(second_handler_id),
            "reason": "调整给更合适的处理人。",
            "expected_ticket_version": 2,
            "expected_assignment_id": first["assignment"]["id"],
            "expected_assignment_version": 1,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "ASSIGNED"
    assert payload["ticket"]["version"] == 3
    assert payload["assignment"]["handler_id"] == str(second_handler_id)
    assert payload["superseded_assignment_id"] == first["assignment"]["id"]

    with Session(engine) as session:
        old = session.get(
            Assignment,
            uuid.UUID(str(first["assignment"]["id"])),
        )
        assert old is not None
        assert old.status == "SUPERSEDED"
        assert old.reason == "调整给更合适的处理人。"
        notifications = session.exec(
            select(Notification).where(
                Notification.ticket_id == uuid.UUID(str(ticket["id"]))
            )
        ).all()
        assert {item.recipient_id for item in notifications} == {
            first_handler_id,
            second_handler_id,
        }
        actions = session.exec(
            select(AuditLog.action).where(
                AuditLog.ticket_id == uuid.UUID(str(ticket["id"]))
            )
        ).all()
        assert "ASSIGNMENT_SUPERSEDED" in actions
        assert actions.count("ASSIGNMENT_CREATED") == 2


def test_vs4_redispatch_from_in_progress_returns_ticket_to_assigned(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    handler_headers = _handler_headers(client)
    with Session(engine) as session:
        first_handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
        second_handler_id = _user(session, VS1_HANDLER_EMAILS[1]).id
    first = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=first_handler_id,
    )
    accepted = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{first['assignment']['id']}/accept"
        ),
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert accepted.status_code == 200

    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(second_handler_id),
            "reason": "处理过程中需要转交。",
            "expected_ticket_version": 3,
            "expected_assignment_id": first["assignment"]["id"],
            "expected_assignment_version": 2,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["ticket"]["status"] == "ASSIGNED"
    assert response.json()["ticket"]["version"] == 4

    with Session(engine) as session:
        old = session.get(
            Assignment,
            uuid.UUID(str(first["assignment"]["id"])),
        )
        assert old is not None
        assert old.status == "SUPERSEDED"
        assert old.version == 3


def test_vs4_submitter_reopens_closed_ticket(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    headers = _submitter_headers(client)
    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        assert ticket_row is not None
        ticket_row.status = "CLOSED"
        ticket_row.version = 2
        session.add(ticket_row)
        session.commit()

    response = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/reopen",
        headers={**headers, "Idempotency-Key": _idempotency_key()},
        json={
            "reason": "问题再次出现，需要重新处理。",
            "expected_ticket_version": 2,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ticket"]["status"] == "PENDING_ASSIGNMENT"
    assert payload["ticket"]["version"] == 3
    assert payload["changed_assignment"] is None

    with Session(engine) as session:
        audits = session.exec(
            select(AuditLog).where(AuditLog.action == "TICKET_REOPENED")
        ).all()
        assert len(audits) == 1
        assert audits[0].detail["note"] == "问题再次出现，需要重新处理。"


def test_vs4_superseded_assignee_cannot_accept_or_complete(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        first_handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
        second_handler_id = _user(session, VS1_HANDLER_EMAILS[1]).id
    first = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=first_handler_id,
    )
    redispatch = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(second_handler_id),
            "reason": "原处理人无法处理。",
            "expected_ticket_version": 2,
            "expected_assignment_id": first["assignment"]["id"],
            "expected_assignment_version": 1,
        },
    )
    assert redispatch.status_code == 201, redispatch.text

    accept = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{first['assignment']['id']}/accept"
        ),
        headers={
            **_handler_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert accept.status_code == 409
    assert accept.json()["error"]["code"] == "ASSIGNMENT_SUPERSEDED"

    complete = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{first['assignment']['id']}/complete"
        ),
        headers={
            **_handler_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "completion_note": "旧记录不得完成。",
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert complete.status_code == 409
    assert complete.json()["error"]["code"] == "ASSIGNMENT_SUPERSEDED"


def test_vs4_redispatch_guards_duplicate_reason_and_expected_assignment(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        first_handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
        second_handler_id = _user(session, VS1_HANDLER_EMAILS[1]).id
    first = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=first_handler_id,
    )

    duplicate = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(first_handler_id),
            "reason": "重复目标。",
            "expected_ticket_version": 2,
            "expected_assignment_id": first["assignment"]["id"],
            "expected_assignment_version": 1,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_ASSIGNMENT"

    missing_reason = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(second_handler_id),
            "reason": None,
            "expected_ticket_version": 2,
            "expected_assignment_id": first["assignment"]["id"],
            "expected_assignment_version": 1,
        },
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["error"]["code"] == "REASON_REQUIRED"

    missing_assignment_version = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
        headers={
            **_dispatcher_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "mode": "MANUAL",
            "handler_id": str(second_handler_id),
            "reason": "重新分配。",
            "expected_ticket_version": 2,
            "expected_assignment_id": first["assignment"]["id"],
            "expected_assignment_version": None,
        },
    )
    assert missing_assignment_version.status_code == 422
    assert (
        missing_assignment_version.json()["error"]["code"] == "VALIDATION_ERROR"
    )

    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        old = session.get(
            Assignment,
            uuid.UUID(str(first["assignment"]["id"])),
        )
        assert ticket_row is not None
        assert old is not None
        assert ticket_row.status == "ASSIGNED"
        assert ticket_row.version == 2
        assert old.status == "ASSIGNED"
        assert old.version == 1
        notifications = session.exec(
            select(Notification).where(
                Notification.ticket_id == uuid.UUID(str(ticket["id"]))
            )
        ).all()
        assert len(notifications) == 1


def test_vs4_accept_and_reject_concurrently_only_one_succeeds(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    handler_headers = _handler_headers(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=handler_id,
    )
    assignment_id = dispatched["assignment"]["id"]

    def accept() -> int:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/assignments/{assignment_id}/accept",
                headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
                json={
                    "expected_ticket_version": 2,
                    "expected_assignment_version": 1,
                },
            )
            return response.status_code

    def reject() -> int:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/assignments/{assignment_id}/reject",
                headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
                json={
                    "reason": "并发拒绝。",
                    "expected_ticket_version": 2,
                    "expected_assignment_version": 1,
                },
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        accept_future = executor.submit(accept)
        reject_future = executor.submit(reject)
        statuses = {accept_future.result(), reject_future.result()}

    assert statuses == {200, 409}
    with Session(engine) as session:
        assignment = session.get(
            Assignment,
            uuid.UUID(str(assignment_id)),
        )
        assert assignment is not None
        assert assignment.status in {"ACCEPTED", "REJECTED"}


def test_vs4_reject_and_reopen_missing_reason_use_stable_codes(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    handler_headers = _handler_headers(client)
    with Session(engine) as session:
        handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
    dispatched = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=handler_id,
    )
    reject = client.post(
        (
            f"{settings.API_V1_STR}/assignments/"
            f"{dispatched['assignment']['id']}/reject"
        ),
        headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
        json={
            "expected_ticket_version": 2,
            "expected_assignment_version": 1,
        },
    )
    assert reject.status_code == 422
    assert reject.json()["error"]["code"] == "REASON_REQUIRED"

    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        assert ticket_row is not None
        ticket_row.status = "CLOSED"
        ticket_row.version = 3
        session.add(ticket_row)
        session.commit()
    reopen = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/reopen",
        headers={**_submitter_headers(client), "Idempotency-Key": _idempotency_key()},
        json={"expected_ticket_version": 3},
    )
    assert reopen.status_code == 422
    assert reopen.json()["error"]["code"] == "REASON_REQUIRED"


def test_vs4_accept_and_redispatch_concurrently_are_serializable(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    handler_headers = _handler_headers(client)
    dispatcher_headers = _dispatcher_headers(client)
    with Session(engine) as session:
        first_handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
        second_handler_id = _user(session, VS1_HANDLER_EMAILS[1]).id
    dispatched = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=first_handler_id,
    )
    assignment_id = dispatched["assignment"]["id"]

    def accept() -> tuple[int, str | None]:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/assignments/{assignment_id}/accept",
                headers={**handler_headers, "Idempotency-Key": _idempotency_key()},
                json={
                    "expected_ticket_version": 2,
                    "expected_assignment_version": 1,
                },
            )
            code = (
                response.json().get("error", {}).get("code")
                if response.status_code >= 400
                else None
            )
            return response.status_code, code

    def redispatch() -> tuple[int, str | None]:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/tickets/{ticket['id']}/dispatch",
                headers={
                    **dispatcher_headers,
                    "Idempotency-Key": _idempotency_key(),
                },
                json={
                    "mode": "MANUAL",
                    "handler_id": str(second_handler_id),
                    "reason": "并发重派。",
                    "expected_ticket_version": 2,
                    "expected_assignment_id": assignment_id,
                    "expected_assignment_version": 1,
                },
            )
            code = (
                response.json().get("error", {}).get("code")
                if response.status_code >= 400
                else None
            )
            return response.status_code, code

    with ThreadPoolExecutor(max_workers=2) as executor:
        accept_future = executor.submit(accept)
        redispatch_future = executor.submit(redispatch)
        accept_result = accept_future.result()
        redispatch_result = redispatch_future.result()

    assert {accept_result[0], redispatch_result[0]} in (
        {200, 409},
        {201, 409},
    )
    if accept_result[0] == 200:
        assert redispatch_result == (409, "STALE_VERSION")
    else:
        assert accept_result == (409, "ASSIGNMENT_SUPERSEDED")
    with Session(engine) as session:
        active = session.exec(
            select(Assignment).where(
                Assignment.ticket_id == uuid.UUID(str(ticket["id"])),
                Assignment.status.in_(("ASSIGNED", "ACCEPTED")),
            )
        ).all()
        assert len(active) == 1


def test_vs4_comment_and_close_concurrently_only_one_wins(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    submitter_headers = _submitter_headers(client)
    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        assert ticket_row is not None
        ticket_row.status = "PENDING_CONFIRMATION"
        ticket_row.version = 4
        session.add(ticket_row)
        session.commit()

    def comment() -> int:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/tickets/{ticket['id']}/comments",
                headers={
                    **submitter_headers,
                    "Idempotency-Key": _idempotency_key(),
                },
                json={
                    "body": "关闭前补充说明。",
                    "expected_ticket_version": 4,
                },
            )
            return response.status_code

    def close() -> int:
        with TestClient(app) as local_client:
            response = local_client.post(
                f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/close",
                headers={
                    **submitter_headers,
                    "Idempotency-Key": _idempotency_key(),
                },
                json={
                    "resolution_note": "并发关闭。",
                    "expected_ticket_version": 4,
                },
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        comment_future = executor.submit(comment)
        close_future = executor.submit(close)
        statuses = {comment_future.result(), close_future.result()}
    assert statuses in ({200, 409}, {201, 409})

    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        assert ticket_row is not None

        comments = session.exec(
            select(Comment).where(
                Comment.ticket_id == uuid.UUID(str(ticket["id"]))
            )
        ).all()
        assert not (ticket_row.status == "CLOSED" and comments)


def test_vs4_redispatch_notification_failure_rolls_back_supersede(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        first_handler_id = _user(session, VS1_HANDLER_EMAILS[0]).id
        second_handler_id = _user(session, VS1_HANDLER_EMAILS[1]).id
    first = _dispatch(
        client,
        ticket_id=ticket["id"],
        handler_id=first_handler_id,
    )

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
                "handler_id": str(second_handler_id),
                "reason": "触发失败回滚。",
                "expected_ticket_version": 2,
                "expected_assignment_id": first["assignment"]["id"],
                "expected_assignment_version": 1,
            },
        )
    assert response.status_code == 500

    with Session(engine) as session:
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        old = session.get(
            Assignment,
            uuid.UUID(str(first["assignment"]["id"])),
        )
        assert ticket_row is not None
        assert old is not None
        assert ticket_row.status == "ASSIGNED"
        assert ticket_row.version == 2
        assert old.status == "ASSIGNED"
        assert old.version == 1
        assert len(session.exec(select(Assignment)).all()) == 1
        assert (
            session.exec(
                select(AuditLog).where(AuditLog.action == "ASSIGNMENT_SUPERSEDED")
            ).all()
            == []
        )


def test_vs4_reopen_permissions_and_history_preservation(
    client: TestClient,
) -> None:
    ticket = _create_ticket(client)
    with Session(engine) as session:
        handler = _user(session, VS1_HANDLER_EMAILS[0])
        dispatcher = _user(session, VS1_DISPATCHER_EMAIL)
        ticket_row = session.get(Ticket, uuid.UUID(str(ticket["id"])))
        assert ticket_row is not None
        ticket_row.status = "CLOSED"
        ticket_row.version = 2
        session.add(ticket_row)
        assignment = Assignment(
            ticket_id=ticket_row.id,
            handler_id=handler.id,
            assigned_by_id=dispatcher.id,
            status="COMPLETED",
            dispatch_mode="MANUAL",
            strategy_code="MANUAL",
            strategy_version="v1",
            completion_note="历史处理说明。",
            finished_at=datetime.now(UTC),
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)
        assignment_id = assignment.id

    handler_reopen = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/reopen",
        headers={
            **_handler_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "reason": "Handler 不能重开。",
            "expected_ticket_version": 2,
        },
    )
    assert handler_reopen.status_code == 403
    assert handler_reopen.json()["error"]["code"] == "ACTION_FORBIDDEN"

    invisible_reopen = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/reopen",
        headers={
            **_handler_headers(client, 1),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "reason": "不可见用户不能重开。",
            "expected_ticket_version": 2,
        },
    )
    assert invisible_reopen.status_code == 404
    assert invisible_reopen.json()["error"]["code"] == "TICKET_NOT_FOUND"

    reopened = client.post(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/actions/reopen",
        headers={
            **_submitter_headers(client),
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "reason": "提交人重新打开。",
            "expected_ticket_version": 2,
        },
    )
    assert reopened.status_code == 200
    history = client.get(
        f"{settings.API_V1_STR}/tickets/{ticket['id']}/assignments",
        headers=_submitter_headers(client),
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [
        str(assignment_id)
    ]
    assert history.json()["items"][0]["status"] == "COMPLETED"


def test_vs4_openapi_adds_exception_actions_without_auto_dispatch(
    client: TestClient,
) -> None:
    spec = client.get(f"{settings.API_V1_STR}/openapi.json").json()
    assert (
        f"{settings.API_V1_STR}/assignments/{{assignment_id}}/reject"
        in spec["paths"]
    )
    assert (
        f"{settings.API_V1_STR}/tickets/{{ticket_id}}/actions/reopen"
        in spec["paths"]
    )
    dispatch_schema = spec["components"]["schemas"]["ManualDispatchRequest"]
    assert dispatch_schema["properties"]["mode"]["const"] == "MANUAL"
