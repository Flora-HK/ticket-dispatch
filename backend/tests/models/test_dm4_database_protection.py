"""DM4 数据库保护：审计不可变、关键约束与索引收口。"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app import crud
from app.models import AuditLog, User, UserCreate


def _create_user(session: Session, email: str = "dm4@example.com") -> User:
    return crud.create_user(
        session=session,
        user_create=UserCreate(email=email, password="changethis-password"),
    )


def _create_audit(session: Session, actor: User) -> AuditLog:
    audit = AuditLog(
        actor_user_id=actor.id,
        actor_type="USER",
        action="TICKET_CREATED",
        entity_type="TICKET",
        entity_id=uuid.uuid4(),
        outcome="SUCCESS",
        request_id=uuid.uuid4(),
        detail={"changed_fields": ["status"]},
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return audit


def test_dm4_audit_log_rejects_update_and_preserves_original_row(
    clean_db: Session,
) -> None:
    actor = _create_user(clean_db)
    audit = _create_audit(clean_db, actor)

    with pytest.raises(DBAPIError, match="audit_log is append-only"):
        clean_db.execute(
            sa.text(
                "update audit_log set outcome = 'FAILED' where id = :audit_id"
            ),
            {"audit_id": audit.id},
        )
    clean_db.rollback()

    stored = clean_db.exec(select(AuditLog).where(AuditLog.id == audit.id)).one()
    assert stored.outcome == "SUCCESS"


def test_dm4_audit_log_rejects_delete_and_preserves_original_row(
    clean_db: Session,
) -> None:
    actor = _create_user(clean_db)
    audit = _create_audit(clean_db, actor)

    with pytest.raises(DBAPIError, match="audit_log is append-only"):
        clean_db.execute(
            sa.text("delete from audit_log where id = :audit_id"),
            {"audit_id": audit.id},
        )
    clean_db.rollback()

    stored = clean_db.exec(select(AuditLog).where(AuditLog.id == audit.id)).one()
    assert stored.id == audit.id


def test_dm4_audit_trigger_is_installed_and_enabled(clean_db: Session) -> None:
    connection = clean_db.connection()
    trigger = connection.execute(
        sa.text(
            "select t.tgenabled, pg_get_triggerdef(t.oid), p.proname "
            "from pg_trigger t "
            "join pg_class c on c.oid = t.tgrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "join pg_proc p on p.oid = t.tgfoid "
            "where n.nspname = 'public' "
            "and c.relname = 'audit_log' "
            "and t.tgname = 'audit_log_append_only'"
        )
    ).one()

    assert trigger.tgenabled == "O"
    assert "BEFORE DELETE OR UPDATE" in trigger[1]
    assert trigger.proname == "prevent_audit_log_mutation"


def test_dm4_contract_indexes_and_unique_constraints_exist(clean_db: Session) -> None:
    connection = clean_db.connection()
    index_defs = dict(
        connection.execute(
            sa.text(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public'"
            )
        ).all()
    )

    assert {
        "uq_assignment_ticket_active",
        "ix_assignment_ticket_assigned_at",
        "ix_assignment_handler_status_assigned_at",
        "ix_ticket_team_status_updated_id",
        "ix_ticket_submitter_updated_id",
        "ix_comment_ticket_created_id",
        "uq_notification_recipient_assignment_type",
        "ix_notification_recipient_created_at",
        "uq_idempotency_actor_scope_key",
        "ix_idempotency_record_expires_at",
        "ix_audit_log_entity_created_at",
        "ix_audit_log_ticket_created_at",
        "ix_audit_log_actor_created_at",
        "ix_audit_log_request_id",
    } <= index_defs.keys()

    assignment_active_index = index_defs["uq_assignment_ticket_active"]
    assert "UNIQUE INDEX" in assignment_active_index
    assert "'ASSIGNED'" in assignment_active_index
    assert "'ACCEPTED'" in assignment_active_index

    constraint_names = set(
        connection.execute(
            sa.text(
                "select conname from pg_constraint "
                "where conrelid in ("
                "'notification'::regclass, "
                "'idempotency_record'::regclass, "
                "'assignment'::regclass"
                ")"
            )
        ).scalars()
    )
    assert {
        "uq_notification_recipient_assignment_type",
        "uq_idempotency_actor_scope_key",
    } <= constraint_names


def test_dm4_dm1_to_dm4_tables_remain_available(clean_db: Session) -> None:
    table_names = set(sa.inspect(clean_db.connection()).get_table_names())
    assert {
        "user",
        "user_role",
        "team",
        "team_membership",
        "ticket",
        "assignment",
        "comment",
        "audit_log",
        "notification",
        "idempotency_record",
        "item",
    } <= table_names
