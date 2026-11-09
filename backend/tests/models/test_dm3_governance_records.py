"""DM3 数据库约束：审计、通知与幂等记录。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.models import (
    Assignment,
    AuditLog,
    IdempotencyRecord,
    Notification,
    Team,
    Ticket,
    User,
    UserCreate,
)


def _create_user(session: Session, email: str = "dm3@example.com") -> User:
    return crud.create_user(
        session=session,
        user_create=UserCreate(email=email, password="changethis-password"),
    )


def _create_ticket(session: Session, submitter: User, team: Team) -> Ticket:
    ticket = Ticket(
        team_id=team.id,
        submitter_id=submitter.id,
        title="审计测试工单",
        description="用于验证审计、通知与幂等数据结构。",
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def _audit_log(
    *,
    actor: User | None,
    ticket_id: uuid.UUID | None = None,
    action: str = "TICKET_CREATED",
    entity_type: str = "TICKET",
    entity_id: uuid.UUID | None = None,
    entity_key: dict[str, str] | None = None,
    actor_type: str = "USER",
    outcome: str = "SUCCESS",
    error_code: str | None = None,
) -> AuditLog:
    return AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_key=entity_key,
        ticket_id=ticket_id,
        before_state=None,
        after_state={"status": "PENDING_ASSIGNMENT", "version": 1},
        outcome=outcome,
        error_code=error_code,
        request_id=uuid.uuid4(),
        detail={"changed_fields": ["status"]},
    )


def _notification(
    *,
    recipient: User,
    ticket: Ticket,
    assignment_id: uuid.UUID,
    notification_type: str = "ASSIGNMENT_RECEIVED",
) -> Notification:
    return Notification(
        recipient_id=recipient.id,
        ticket_id=ticket.id,
        assignment_id=assignment_id,
        notification_type=notification_type,
        payload={"title": "收到新工单", "message": "请及时处理"},
    )


def _create_assignment(
    session: Session,
    submitter: User,
    handler: User,
    team: Team,
) -> tuple[Ticket, Assignment]:
    ticket = _create_ticket(session, submitter, team)
    assignment = Assignment(
        ticket_id=ticket.id,
        handler_id=handler.id,
        assigned_by_id=submitter.id,
        dispatch_mode="MANUAL",
        strategy_code="MANUAL",
        strategy_version="v1",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return ticket, assignment


def test_dm3_audit_log_uses_incrementing_bigint_and_stores_compound_key(
    clean_db: Session,
) -> None:
    user = _create_user(clean_db)
    first = _audit_log(
        actor=user,
        action="USER_ROLES_CHANGED",
        entity_type="USER_ROLE",
        entity_key={"user_id": str(user.id), "role_code": "ADMIN"},
    )
    second = _audit_log(
        actor=user,
        action="USER_ROLES_CHANGED",
        entity_type="USER_ROLE",
        entity_key={"user_id": str(user.id), "role_code": "HANDLER"},
    )
    clean_db.add(first)
    clean_db.add(second)
    clean_db.commit()
    clean_db.refresh(first)
    clean_db.refresh(second)

    assert first.id is not None
    assert second.id is not None
    assert second.id > first.id
    assert first.entity_key == {
        "user_id": str(user.id),
        "role_code": "ADMIN",
    }


def test_dm3_audit_actor_type_and_identity_are_consistent(clean_db: Session) -> None:
    user = _create_user(clean_db)
    system_log = _audit_log(
        actor=None,
        actor_type="SYSTEM",
        action="AUTO_ASSIGN_FAILED",
        outcome="FAILED",
        error_code="NO_ELIGIBLE_HANDLER",
    )
    clean_db.add(system_log)
    clean_db.commit()
    assert system_log.actor_user_id is None

    invalid_cases = (
        _audit_log(actor=None, actor_type="USER"),
        _audit_log(actor=user, actor_type="SYSTEM"),
    )
    for audit in invalid_cases:
        clean_db.add(audit)
        with pytest.raises(IntegrityError):
            clean_db.commit()
        clean_db.rollback()


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    (
        # agent 类型的非法值也可能先触发 Actor 身份绑定约束。
        ("actor_type", "ROBOT", "ck_audit_log_actor_"),
        ("action", "UNKNOWN_ACTION", "ck_audit_log_action"),
        ("entity_type", "COMMENT", "ck_audit_log_entity_type"),
        ("outcome", "UNKNOWN", "ck_audit_log_outcome"),
    ),
)
def test_dm3_audit_enum_checks_reject_unknown_values(
    clean_db: Session,
    field: str,
    value: str,
    constraint: str,
) -> None:
    user = _create_user(clean_db)
    values = {
        "actor_user_id": user.id,
        "actor_type": "USER",
        "action": "TICKET_CREATED",
        "entity_type": "TICKET",
        "outcome": "SUCCESS",
        "request_id": uuid.uuid4(),
    }
    values[field] = value
    clean_db.add(AuditLog(**values))
    with pytest.raises(IntegrityError, match=constraint):
        clean_db.commit()
    clean_db.rollback()


def test_dm3_audit_detail_defaults_to_empty_json(clean_db: Session) -> None:
    user = _create_user(clean_db)
    request_id = uuid.uuid4()
    # 直接通过 SQL 省略 detail，验证迁移中的 PostgreSQL server default。
    detail_type = clean_db.execute(
        sa.text(
            "insert into audit_log ("
            "actor_user_id, actor_type, action, entity_type, outcome, "
            "request_id, created_at"
            ") values ("
            ":actor_user_id, 'USER', 'TICKET_CREATED', 'TICKET', 'SUCCESS', "
            ":request_id, :created_at"
            ") returning jsonb_typeof(detail)"
        ),
        {
            "actor_user_id": user.id,
            "request_id": request_id,
            "created_at": datetime.now(UTC),
        },
    ).scalar_one()
    clean_db.commit()
    assert detail_type == "object"


def test_dm3_duplicate_assignment_notification_is_rejected(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    team = crud.create_team(session=clean_db, name="审计通知团队")
    ticket, assignment = _create_assignment(
        clean_db,
        submitter=submitter,
        handler=handler,
        team=team,
    )
    clean_db.add(_notification(recipient=handler, ticket=ticket, assignment_id=assignment.id))
    clean_db.commit()

    clean_db.add(_notification(recipient=handler, ticket=ticket, assignment_id=assignment.id))
    with pytest.raises(IntegrityError, match="uq_notification_recipient_assignment_type"):
        clean_db.commit()
    clean_db.rollback()

    notifications = clean_db.exec(
        select(Notification).where(Notification.assignment_id == assignment.id)
    ).all()
    assert len(notifications) == 1


def test_dm3_unknown_notification_type_is_rejected(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    team = crud.create_team(session=clean_db, name="通知类型团队")
    ticket, assignment = _create_assignment(
        clean_db,
        submitter=submitter,
        handler=handler,
        team=team,
    )
    clean_db.add(
        _notification(
            recipient=handler,
            ticket=ticket,
            assignment_id=assignment.id,
            notification_type="EMAIL_SENT",
        )
    )
    with pytest.raises(IntegrityError, match="ck_notification_type"):
        clean_db.commit()
    clean_db.rollback()


def test_dm3_idempotency_scope_and_key_are_unique(clean_db: Session) -> None:
    actor = _create_user(clean_db)
    created_at = datetime.now(UTC)
    first = IdempotencyRecord(
        actor_user_id=actor.id,
        command_scope="DISPATCH_TICKET",
        idempotency_key="dispatch-key-1",
        request_hash="a" * 64,
        response_status=201,
        response_body={"resource_id": str(uuid.uuid4())},
        resource_type="ASSIGNMENT",
        created_at=created_at,
        expires_at=created_at + timedelta(days=7),
    )
    clean_db.add(first)
    clean_db.commit()

    duplicate = IdempotencyRecord(
        actor_user_id=actor.id,
        command_scope="DISPATCH_TICKET",
        idempotency_key="dispatch-key-1",
        request_hash="b" * 64,
        response_status=201,
        response_body={},
        created_at=created_at,
        expires_at=created_at + timedelta(days=7),
    )
    clean_db.add(duplicate)
    with pytest.raises(IntegrityError, match="uq_idempotency_actor_scope_key"):
        clean_db.commit()
    clean_db.rollback()

    different_scope = IdempotencyRecord(
        actor_user_id=actor.id,
        command_scope="COMMENT_TICKET",
        idempotency_key="dispatch-key-1",
        request_hash="c" * 64,
        response_status=201,
        response_body={},
        created_at=created_at,
        expires_at=created_at + timedelta(days=7),
    )
    clean_db.add(different_scope)
    clean_db.commit()


def test_dm3_idempotency_expiry_must_be_exactly_seven_days(clean_db: Session) -> None:
    actor = _create_user(clean_db)
    created_at = datetime.now(UTC)
    invalid = IdempotencyRecord(
        actor_user_id=actor.id,
        command_scope="DISPATCH_TICKET",
        idempotency_key="wrong-expiry",
        request_hash="d" * 64,
        response_status=201,
        response_body={},
        created_at=created_at,
        expires_at=created_at + timedelta(days=6),
    )
    clean_db.add(invalid)
    with pytest.raises(IntegrityError, match="ck_idempotency_expiry"):
        clean_db.commit()
    clean_db.rollback()


def test_dm3_idempotency_response_status_is_valid_http_code(clean_db: Session) -> None:
    actor = _create_user(clean_db)
    created_at = datetime.now(UTC)
    clean_db.add(
        IdempotencyRecord(
            actor_user_id=actor.id,
            command_scope="DISPATCH_TICKET",
            idempotency_key="bad-status",
            request_hash="e" * 64,
            response_status=99,
            response_body={},
            created_at=created_at,
            expires_at=created_at + timedelta(days=7),
        )
    )
    with pytest.raises(IntegrityError, match="ck_idempotency_response_status"):
        clean_db.commit()
    clean_db.rollback()


def test_dm3_governance_records_block_parent_deletion(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    team = crud.create_team(session=clean_db, name="删除保护团队")
    ticket, assignment = _create_assignment(
        clean_db,
        submitter=submitter,
        handler=handler,
        team=team,
    )
    created_at = datetime.now(UTC)
    clean_db.add(
        _audit_log(
            actor=submitter,
            ticket_id=ticket.id,
            entity_id=ticket.id,
        )
    )
    clean_db.add(_notification(recipient=handler, ticket=ticket, assignment_id=assignment.id))
    clean_db.add(
        IdempotencyRecord(
            actor_user_id=submitter.id,
            command_scope="CREATE_COMMENT",
            idempotency_key="protected-parent",
            request_hash="f" * 64,
            response_status=201,
            response_body={},
            created_at=created_at,
            expires_at=created_at + timedelta(days=7),
        )
    )
    clean_db.commit()

    for parent in (ticket, assignment, handler, submitter):
        clean_db.delete(parent)
        with pytest.raises(IntegrityError):
            clean_db.commit()
        clean_db.rollback()

    assert clean_db.get(Ticket, ticket.id) is not None
    assert clean_db.get(User, handler.id) is not None


def test_dm3_unknown_governance_foreign_keys_are_rejected(clean_db: Session) -> None:
    actor = _create_user(clean_db)
    created_at = datetime.now(UTC)
    clean_db.add(
        IdempotencyRecord(
            actor_user_id=uuid.uuid4(),
            command_scope="CREATE_TICKET",
            idempotency_key="unknown-actor",
            request_hash="1" * 64,
            response_status=201,
            response_body={},
            created_at=created_at,
            expires_at=created_at + timedelta(days=7),
        )
    )
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()

    clean_db.add(
        _audit_log(
            actor=actor,
            ticket_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
        )
    )
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()


def test_dm3_required_indexes_and_constraints_exist(clean_db: Session) -> None:
    connection = clean_db.connection()
    index_defs = dict(
        connection.execute(
            sa.text(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public' "
                "and tablename in "
                "('audit_log', 'notification', 'idempotency_record')"
            )
        ).all()
    )
    assert {
        "ix_audit_log_entity_created_at",
        "ix_audit_log_ticket_created_at",
        "ix_audit_log_actor_created_at",
        "ix_audit_log_request_id",
        "uq_notification_recipient_assignment_type",
        "ix_notification_recipient_created_at",
        "uq_idempotency_actor_scope_key",
        "ix_idempotency_record_expires_at",
    } <= index_defs.keys()
    assert "created_at DESC" in index_defs["ix_audit_log_entity_created_at"]
    assert "created_at DESC" in index_defs["ix_notification_recipient_created_at"]

    constraint_names = set(
        connection.execute(
            sa.text(
                "select conname from pg_constraint "
                "where conrelid in ("
                "'audit_log'::regclass, "
                "'notification'::regclass, "
                "'idempotency_record'::regclass"
                ")"
            )
        ).scalars()
    )
    assert {
        "ck_audit_log_actor_type",
        "ck_audit_log_actor_binding",
        "ck_audit_log_action",
        "ck_audit_log_entity_type",
        "ck_audit_log_outcome",
        "ck_notification_type",
        "uq_notification_recipient_assignment_type",
        "ck_idempotency_response_status",
        "ck_idempotency_expiry",
        "uq_idempotency_actor_scope_key",
    } <= constraint_names
