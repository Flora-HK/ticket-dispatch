"""DM2 schema guarantees: Ticket, Assignment and Comment."""

import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import crud
from app.models import Assignment, Comment, Team, Ticket, User, UserCreate


def _create_user(session: Session, email: str = "dm2@example.com") -> User:
    return crud.create_user(
        session=session,
        user_create=UserCreate(email=email, password="changethis-password"),
    )


def _create_ticket(
    session: Session,
    *,
    submitter: User,
    team: Team,
    status: str = "PENDING_ASSIGNMENT",
) -> Ticket:
    ticket = Ticket(
        team_id=team.id,
        submitter_id=submitter.id,
        title="无法登录",
        description="账号登录后持续提示无权限。",
        status=status,
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def _create_assignment(
    session: Session,
    *,
    ticket: Ticket,
    handler: User,
    assigned_by: User,
    status: str = "ASSIGNED",
    dispatch_mode: str = "MANUAL",
    strategy_code: str = "MANUAL",
    reason: str | None = None,
    completion_note: str | None = None,
    finished_at: datetime | None = None,
) -> Assignment:
    assignment = Assignment(
        ticket_id=ticket.id,
        handler_id=handler.id,
        assigned_by_id=assigned_by.id,
        status=status,
        dispatch_mode=dispatch_mode,
        strategy_code=strategy_code,
        strategy_version="v1",
        selection_summary={"candidate_count": 1},
        reason=reason,
        completion_note=completion_note,
        finished_at=finished_at,
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def test_dm2_ticket_defaults_and_has_no_assignee_field(clean_db: Session) -> None:
    submitter = _create_user(clean_db)
    team = crud.create_team(session=clean_db, name="账号与权限")

    ticket = _create_ticket(clean_db, submitter=submitter, team=team)

    assert ticket.status == "PENDING_ASSIGNMENT"
    assert ticket.version == 1
    assert "assignee_id" not in Ticket.model_fields


def test_dm2_ticket_status_check_rejects_unknown_status(clean_db: Session) -> None:
    submitter = _create_user(clean_db)
    team = crud.create_team(session=clean_db, name="账号与权限")
    clean_db.add(
        Ticket(
            team_id=team.id,
            submitter_id=submitter.id,
            title="非法状态",
            description="状态不在契约集合中。",
            status="OPEN",
        )
    )

    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()


def test_dm2_only_one_active_assignment_is_allowed(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="账号与权限")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)
    _create_assignment(
        clean_db,
        ticket=ticket,
        handler=handler,
        assigned_by=dispatcher,
    )

    clean_db.add(
        Assignment(
            ticket_id=ticket.id,
            handler_id=handler.id,
            assigned_by_id=dispatcher.id,
            dispatch_mode="MANUAL",
            strategy_code="MANUAL",
            strategy_version="v1",
        )
    )
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()

    active = clean_db.exec(
        select(Assignment).where(
            Assignment.ticket_id == ticket.id,
            Assignment.status.in_(("ASSIGNED", "ACCEPTED")),
        )
    ).all()
    assert len(active) == 1


def test_dm2_terminal_assignments_can_coexist_as_history(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="硬件支持")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)

    rejected = _create_assignment(
        clean_db,
        ticket=ticket,
        handler=handler,
        assigned_by=dispatcher,
        status="REJECTED",
        reason="当前无处理条件",
    )
    superseded = _create_assignment(
        clean_db,
        ticket=ticket,
        handler=handler,
        assigned_by=dispatcher,
        status="SUPERSEDED",
        reason="转交其他处理人",
    )

    history = clean_db.exec(
        select(Assignment).where(Assignment.ticket_id == ticket.id)
    ).all()
    assert {item.status for item in history} == {"REJECTED", "SUPERSEDED"}
    assert rejected.id != superseded.id


def test_dm2_rejected_and_superseded_require_reason(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="网络支持")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)

    for status in ("REJECTED", "SUPERSEDED"):
        clean_db.add(
            Assignment(
                ticket_id=ticket.id,
                handler_id=handler.id,
                assigned_by_id=dispatcher.id,
                status=status,
                dispatch_mode="MANUAL",
                strategy_code="MANUAL",
                strategy_version="v1",
            )
        )
        with pytest.raises(IntegrityError):
            clean_db.commit()
        clean_db.rollback()

    clean_db.add(
        Assignment(
            ticket_id=ticket.id,
            handler_id=handler.id,
            assigned_by_id=dispatcher.id,
            status="REJECTED",
            dispatch_mode="MANUAL",
            strategy_code="MANUAL",
            strategy_version="v1",
            reason="   ",
        )
    )
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()


def test_dm2_completed_requires_note_and_finished_at(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="终端支持")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)

    invalid_cases = (
        {"completion_note": None, "finished_at": datetime.now(UTC)},
        {"completion_note": "已重置密码", "finished_at": None},
        {"completion_note": "   ", "finished_at": datetime.now(UTC)},
    )
    for values in invalid_cases:
        clean_db.add(
            Assignment(
                ticket_id=ticket.id,
                handler_id=handler.id,
                assigned_by_id=dispatcher.id,
                status="COMPLETED",
                dispatch_mode="MANUAL",
                strategy_code="MANUAL",
                strategy_version="v1",
                **values,
            )
        )
        with pytest.raises(IntegrityError):
            clean_db.commit()
        clean_db.rollback()

    completed = _create_assignment(
        clean_db,
        ticket=ticket,
        handler=handler,
        assigned_by=dispatcher,
        status="COMPLETED",
        completion_note="已重置密码并验证登录。",
        finished_at=datetime.now(UTC),
    )
    assert completed.status == "COMPLETED"


def test_dm2_assignment_enums_are_database_constrained(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="办公软件")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)

    invalid_cases = (
        {"status": "OPEN", "dispatch_mode": "MANUAL", "strategy_code": "MANUAL"},
        {"status": "ASSIGNED", "dispatch_mode": "BATCH", "strategy_code": "MANUAL"},
        {
            "status": "ASSIGNED",
            "dispatch_mode": "AUTO",
            "strategy_code": "ROUND_ROBIN",
        },
    )
    for values in invalid_cases:
        clean_db.add(
            Assignment(
                ticket_id=ticket.id,
                handler_id=handler.id,
                assigned_by_id=dispatcher.id,
                strategy_version="v1",
                **values,
            )
        )
        with pytest.raises(IntegrityError):
            clean_db.commit()
        clean_db.rollback()


def test_dm2_comment_rejects_blank_and_oversized_body(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    team = crud.create_team(session=clean_db, name="账号与权限")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)

    for body in ("   ", "x" * 5001):
        clean_db.add(Comment(ticket_id=ticket.id, author_id=submitter.id, body=body))
        with pytest.raises(IntegrityError):
            clean_db.commit()
        clean_db.rollback()

    comment = Comment(
        ticket_id=ticket.id,
        author_id=submitter.id,
        body="补充：重置密码后已恢复。",
    )
    clean_db.add(comment)
    clean_db.commit()
    clean_db.refresh(comment)
    assert comment.id is not None


def test_dm2_business_history_fks_block_parent_deletion(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="身份认证")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)
    _create_assignment(
        clean_db,
        ticket=ticket,
        handler=handler,
        assigned_by=dispatcher,
    )
    clean_db.add(
        Comment(
            ticket_id=ticket.id,
            author_id=submitter.id,
            body="已补充错误截图。",
        )
    )
    clean_db.commit()

    for parent in (ticket, team, submitter, handler):
        clean_db.delete(parent)
        with pytest.raises(IntegrityError):
            clean_db.commit()
        clean_db.rollback()

    assert clean_db.get(Ticket, ticket.id) is not None
    assert clean_db.get(Team, team.id) is not None
    assert clean_db.get(User, submitter.id) is not None


def test_dm2_assignment_accepts_foreign_keys_and_json_summary(clean_db: Session) -> None:
    submitter = _create_user(clean_db, "submitter@example.com")
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="网络支持")
    ticket = _create_ticket(clean_db, submitter=submitter, team=team)

    assignment = Assignment(
        ticket_id=ticket.id,
        handler_id=handler.id,
        assigned_by_id=dispatcher.id,
        dispatch_mode="AUTO",
        strategy_code="LEAST_OPEN_TICKET",
        strategy_version="v1",
        selection_summary={"candidate_count": 2, "ranked": [str(handler.id)]},
    )
    clean_db.add(assignment)
    clean_db.commit()
    clean_db.refresh(assignment)

    assert assignment.version == 1
    assert assignment.selection_summary == {
        "candidate_count": 2,
        "ranked": [str(handler.id)],
    }


def test_dm2_unknown_foreign_keys_are_rejected(clean_db: Session) -> None:
    submitter = _create_user(clean_db)
    handler = _create_user(clean_db, "handler@example.com")
    dispatcher = _create_user(clean_db, "dispatcher@example.com")
    team = crud.create_team(session=clean_db, name="未知引用")

    clean_db.add(
        Ticket(
            team_id=uuid.uuid4(),
            submitter_id=submitter.id,
            title="未知 Team",
            description="该 Team 不存在。",
        )
    )
    with pytest.raises(IntegrityError):
        clean_db.commit()
    clean_db.rollback()

    ticket = _create_ticket(clean_db, submitter=submitter, team=team)
    clean_db.add(
        Assignment(
            ticket_id=ticket.id,
            handler_id=handler.id,
            assigned_by_id=dispatcher.id,
            dispatch_mode="MANUAL",
            strategy_code="MANUAL",
            strategy_version="v1",
        )
    )
    clean_db.flush()
    with pytest.raises(IntegrityError):
        clean_db.execute(
            sa.text(
                "update assignment set handler_id = :handler_id "
                "where ticket_id = :ticket_id"
            ),
            {"handler_id": uuid.uuid4(), "ticket_id": ticket.id},
        )
    clean_db.rollback()


def test_dm2_critical_constraints_and_indexes_exist(clean_db: Session) -> None:
    connection = clean_db.connection()

    index_defs = dict(
        connection.execute(
            sa.text(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public' "
                "and tablename in ('ticket', 'assignment', 'comment')"
            )
        ).all()
    )
    assert {
        "ix_ticket_team_status_updated_id",
        "ix_ticket_submitter_updated_id",
        "uq_assignment_ticket_active",
        "ix_assignment_ticket_assigned_at",
        "ix_assignment_handler_status_assigned_at",
        "ix_comment_ticket_created_id",
    } <= index_defs.keys()
    assert "UNIQUE INDEX" in index_defs["uq_assignment_ticket_active"]
    assert "WHERE" in index_defs["uq_assignment_ticket_active"]
    assert "'ASSIGNED'" in index_defs["uq_assignment_ticket_active"]
    assert "'ACCEPTED'" in index_defs["uq_assignment_ticket_active"]
    assert "updated_at DESC" in index_defs["ix_ticket_team_status_updated_id"]
    assert "id DESC" in index_defs["ix_ticket_team_status_updated_id"]

    check_names = set(
        connection.execute(
            sa.text(
                "select conname from pg_constraint "
                "where conrelid in "
                "('ticket'::regclass, 'assignment'::regclass, 'comment'::regclass) "
                "and contype = 'c'"
            )
        ).scalars()
    )
    assert {
        "ck_ticket_status",
        "ck_ticket_title_length",
        "ck_ticket_description_length",
        "ck_assignment_status",
        "ck_assignment_dispatch_mode",
        "ck_assignment_strategy_code",
        "ck_assignment_terminal_reason",
        "ck_assignment_completed_fields",
        "ck_comment_body",
    } <= check_names
