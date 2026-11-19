import base64
import binascii
import hashlib
import json
import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from app.api.deps import ActorContext
from app.core.errors import APIError
from app.models import (
    AcceptAssignmentRequest,
    ActiveAssignmentResponse,
    Assignment,
    AssignmentPage,
    AssignmentPublic,
    AuditLog,
    CandidateRankingEntry,
    CloseTicketRequest,
    CompleteAssignmentRequest,
    DispatchCandidateListResponse,
    DispatchCandidatePublic,
    DispatchExplanation,
    DispatchRequest,
    DispatchResponse,
    Notification,
    RejectAssignmentRequest,
    ReopenTicketRequest,
    Team,
    TeamMembership,
    Ticket,
    TicketMutationResponse,
    TicketStatePublic,
    TicketStatus,
    User,
    UserRole,
    UserSummary,
    get_datetime_utc,
)
from app.services.dispatch_strategy import (
    DispatchCandidateData,
    DispatchDecision,
    LeastOpenTicketStrategy,
    ManualDispatchStrategy,
)
from app.services.idempotency import (
    begin_idempotent_command,
    finish_idempotent_command,
)
from app.services.tickets import ticket_visibility_condition


def _candidate_load_subquery():
    """负载只统计未关闭工单上的当前有效派发，已完成记录不再占用容量。"""

    return (
        select(
            col(Assignment.handler_id).label("handler_id"),
            func.count(func.distinct(Assignment.ticket_id)).label("open_ticket_count"),
        )
        .join(Ticket, col(Assignment.ticket_id) == col(Ticket.id))
        .where(
            col(Assignment.status).in_(("ASSIGNED", "ACCEPTED")),
            col(Ticket.status) != "CLOSED",
        )
        .group_by(col(Assignment.handler_id))
        .subquery()
    )


def read_dispatch_candidates(
    *,
    session: Session,
    ticket_id: uuid.UUID,
) -> DispatchCandidateListResponse:
    """按负载、最近派发时间和 UUID 稳定排序，供派单员选择处理人。"""

    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise APIError(
            status_code=404,
            code="TICKET_NOT_FOUND",
            message="The ticket does not exist.",
        )
    team = session.get(Team, ticket.team_id)
    if (
        team is None
        or not team.is_active
        or ticket.status not in ("PENDING_ASSIGNMENT", "ASSIGNED", "IN_PROGRESS")
    ):
        return DispatchCandidateListResponse(
            ticket_id=ticket.id,
            team_id=ticket.team_id,
            items=[],
            candidate_count=0,
        )

    load = _candidate_load_subquery()
    statement = (
        select(
            User,
            TeamMembership,
            func.coalesce(load.c.open_ticket_count, 0).label("open_ticket_count"),
        )
        .join(TeamMembership, col(TeamMembership.user_id) == col(User.id))
        .join(UserRole, col(UserRole.user_id) == col(User.id))
        .outerjoin(load, load.c.handler_id == User.id)
        .where(
            col(TeamMembership.team_id) == ticket.team_id,
            col(TeamMembership.is_available).is_(True),
            col(User.is_active).is_(True),
            col(User.id) != ticket.submitter_id,
            col(UserRole.role_code) == "HANDLER",
        )
        .order_by(
            func.coalesce(load.c.open_ticket_count, 0),
            col(TeamMembership.last_assigned_at).asc().nullsfirst(),
            col(User.id),
        )
    )
    rows = list(session.exec(statement).all())
    items = [
        DispatchCandidatePublic(
            handler_id=user.id,
            handler=UserSummary.model_validate(user),
            open_ticket_count=int(open_ticket_count),
            last_assigned_at=membership.last_assigned_at,
            rank=rank,
        )
        for rank, (user, membership, open_ticket_count) in enumerate(rows, start=1)
    ]
    return DispatchCandidateListResponse(
        ticket_id=ticket.id,
        team_id=ticket.team_id,
        items=items,
        candidate_count=len(items),
    )


def _team_lock_id(team_id: uuid.UUID) -> int:
    digest = hashlib.sha256(f"team:{team_id}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _assignment_public(
    *,
    session: Session,
    assignment: Assignment,
) -> AssignmentPublic:
    handler = session.get(User, assignment.handler_id)
    assigned_by = session.get(User, assignment.assigned_by_id)
    if handler is None or assigned_by is None:
        raise RuntimeError("assignment user relationship is missing")
    return AssignmentPublic(
        id=assignment.id,
        ticket_id=assignment.ticket_id,
        handler_id=assignment.handler_id,
        handler=UserSummary.model_validate(handler),
        assigned_by_id=assignment.assigned_by_id,
        assigned_by=UserSummary.model_validate(assigned_by),
        status=assignment.status,
        dispatch_mode=assignment.dispatch_mode,
        strategy_code=assignment.strategy_code,
        strategy_version=assignment.strategy_version,
        reason=assignment.reason,
        completion_note=assignment.completion_note,
        assigned_at=assignment.assigned_at,
        responded_at=assignment.responded_at,
        finished_at=assignment.finished_at,
        version=assignment.version,
    )


def _ensure_ticket_visible(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
) -> Ticket:
    ticket = session.exec(
        select(Ticket).where(
            col(Ticket.id) == ticket_id,
            ticket_visibility_condition(actor),
        )
    ).first()
    if ticket is None:
        raise APIError(
            status_code=404,
            code="TICKET_NOT_FOUND",
            message="The ticket does not exist.",
        )
    return ticket


def _assignment_cursor(
    *,
    assignment: Assignment,
    ticket_id: uuid.UUID,
    status_filter: str | None,
) -> str:
    payload = json.dumps(
        {
            "ticket_id": str(ticket_id),
            "status": status_filter,
            "assigned_at": assignment.assigned_at.isoformat(),
            "id": str(assignment.id),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_assignment_cursor(
    *,
    cursor: str,
    ticket_id: uuid.UUID,
    status_filter: str | None,
) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if (
            payload["ticket_id"] != str(ticket_id)
            or payload["status"] != status_filter
        ):
            raise ValueError("cursor is bound to another query")
        return datetime.fromisoformat(payload["assigned_at"]), uuid.UUID(
            payload["id"]
        )
    except (
        binascii.Error,
        UnicodeDecodeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise APIError(
            status_code=422,
            code="INVALID_CURSOR",
            message="The cursor is invalid for this query.",
        ) from exc


def read_assignment_page(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    status_filter: str | None,
    cursor: str | None,
    limit: int,
) -> AssignmentPage:
    """按派发时间倒序返回完整历史，并继承 Ticket 的资源级可见性。"""

    _ensure_ticket_visible(session=session, actor=actor, ticket_id=ticket_id)
    if status_filter is not None and status_filter not in {
        "ASSIGNED",
        "ACCEPTED",
        "REJECTED",
        "COMPLETED",
        "SUPERSEDED",
    }:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The assignment status filter is invalid.",
        )
    statement = select(Assignment).where(col(Assignment.ticket_id) == ticket_id)
    if status_filter is not None:
        statement = statement.where(col(Assignment.status) == status_filter)
    if cursor is not None:
        assigned_at, assignment_id = _decode_assignment_cursor(
            cursor=cursor,
            ticket_id=ticket_id,
            status_filter=status_filter,
        )
        statement = statement.where(
            or_(
                col(Assignment.assigned_at) < assigned_at,
                and_(
                    col(Assignment.assigned_at) == assigned_at,
                    col(Assignment.id) < assignment_id,
                ),
            )
        )
    statement = statement.order_by(
        col(Assignment.assigned_at).desc(),
        col(Assignment.id).desc(),
    ).limit(limit + 1)
    rows = list(session.exec(statement).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        _assignment_cursor(
            assignment=page[-1],
            ticket_id=ticket_id,
            status_filter=status_filter,
        )
        if has_more and page
        else None
    )
    return AssignmentPage(
        items=[
            _assignment_public(session=session, assignment=assignment)
            for assignment in page
        ],
        next_cursor=next_cursor,
    )


def read_active_assignment(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
) -> ActiveAssignmentResponse:
    """当前处理人只由 ASSIGNED/ACCEPTED 历史推导，不读取 Ticket 副本字段。"""

    _ensure_ticket_visible(session=session, actor=actor, ticket_id=ticket_id)
    assignment = session.exec(
        select(Assignment)
        .where(
            col(Assignment.ticket_id) == ticket_id,
            col(Assignment.status).in_(("ASSIGNED", "ACCEPTED")),
        )
        .order_by(
            col(Assignment.assigned_at).desc(),
            col(Assignment.id).desc(),
        )
        .limit(1)
    ).first()
    return ActiveAssignmentResponse(
        ticket_id=ticket_id,
        assignment=(
            _assignment_public(session=session, assignment=assignment)
            if assignment is not None
            else None
        ),
    )


def _ticket_state(ticket: Ticket) -> TicketStatePublic:
    return TicketStatePublic(
        id=ticket.id,
        status=cast(TicketStatus, ticket.status),
        version=ticket.version,
        updated_at=ticket.updated_at,
    )


def _lock_ticket_for_dispatch(
    *,
    session: Session,
    ticket_id: uuid.UUID,
) -> Ticket:
    ticket_ref = session.get(Ticket, ticket_id)
    if ticket_ref is None:
        raise APIError(
            status_code=404,
            code="TICKET_NOT_FOUND",
            message="The ticket does not exist.",
        )
    session.exec(
        select(func.pg_advisory_xact_lock(_team_lock_id(ticket_ref.team_id)))
    ).one()
    ticket = session.exec(
        select(Ticket)
        .where(col(Ticket.id) == ticket_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if ticket.team_id != ticket_ref.team_id:
        raise RuntimeError("ticket team changed while acquiring team lock")
    return ticket


def dispatch_ticket(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    idempotency_key: str,
    dispatch_in: DispatchRequest,
) -> DispatchResponse:
    """执行人工或自动首次派发/重派，并在同一事务更新全部业务事实。"""

    payload = {
        "ticket_id": str(ticket_id),
        **dispatch_in.model_dump(mode="json"),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin() as transaction:
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="DISPATCH_TICKET",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return DispatchResponse.model_validate(reservation.replay.body)

        ticket = _lock_ticket_for_dispatch(session=session, ticket_id=ticket_id)
        if ticket.version != dispatch_in.expected_ticket_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "ticket_id": str(ticket.id),
                    "expected_ticket_version": dispatch_in.expected_ticket_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if ticket.status == "CLOSED":
            raise APIError(
                status_code=409,
                code="TICKET_CLOSED",
                message="Closed tickets cannot be dispatched.",
                details={"ticket_id": str(ticket.id)},
            )
        if ticket.status not in (
            "PENDING_ASSIGNMENT",
            "ASSIGNED",
            "IN_PROGRESS",
        ):
            raise APIError(
                status_code=409,
                code="INVALID_TRANSITION",
                message="The ticket cannot be dispatched in its current state.",
                details={
                    "ticket_id": str(ticket.id),
                    "ticket_status": ticket.status,
                },
            )

        active_assignment = session.exec(
            select(Assignment)
            .where(
                col(Assignment.ticket_id) == ticket.id,
                col(Assignment.status).in_(("ASSIGNED", "ACCEPTED")),
            )
            .order_by(
                col(Assignment.assigned_at).desc(),
                col(Assignment.id).desc(),
            )
            .limit(1)
            .with_for_update()
        ).first()
        prefetched_candidates: DispatchCandidateListResponse | None = None
        prefetched_decision: DispatchDecision | None = None
        superseded_assignment_id: uuid.UUID | None = None
        if ticket.status == "PENDING_ASSIGNMENT" and active_assignment is not None:
            raise APIError(
                status_code=409,
                code="ALREADY_ASSIGNED",
                message="The ticket already has an active assignment.",
                details={"ticket_id": str(ticket.id)},
            )
        if ticket.status in ("ASSIGNED", "IN_PROGRESS"):
            if active_assignment is None:
                raise APIError(
                    status_code=409,
                    code="INVALID_TRANSITION",
                    message="The ticket has no active assignment to replace.",
                    details={"ticket_id": str(ticket.id)},
                )
            if dispatch_in.mode == "AUTO":
                prefetched_candidates = read_dispatch_candidates(
                    session=session,
                    ticket_id=ticket.id,
                )
                prefetched_decision = LeastOpenTicketStrategy().choose(
                    tuple(
                        DispatchCandidateData(
                            handler_id=item.handler_id,
                            open_ticket_count=item.open_ticket_count,
                            last_assigned_at=item.last_assigned_at,
                        )
                        for item in prefetched_candidates.items
                    )
                )
                if (
                    prefetched_decision.selected_handler_id
                    == active_assignment.handler_id
                ):
                    raise APIError(
                        status_code=409,
                        code="DUPLICATE_ASSIGNMENT",
                        message="The selected handler already owns this assignment.",
                        details={
                            "ticket_id": str(ticket.id),
                            "assignment_id": str(active_assignment.id),
                        },
                    )
            if (
                dispatch_in.mode == "MANUAL"
                and active_assignment.handler_id == dispatch_in.handler_id
            ):
                raise APIError(
                    status_code=409,
                    code="DUPLICATE_ASSIGNMENT",
                    message="The selected handler already owns this assignment.",
                    details={
                        "ticket_id": str(ticket.id),
                        "assignment_id": str(active_assignment.id),
                    },
                )
            if dispatch_in.reason is None:
                raise APIError(
                    status_code=422,
                    code="REASON_REQUIRED",
                    message="A reason is required when reassigning a ticket.",
                )
            if (
                dispatch_in.expected_assignment_id is None
                or dispatch_in.expected_assignment_version is None
            ):
                raise APIError(
                    status_code=422,
                    code="VALIDATION_ERROR",
                    message="The active assignment version is required.",
                    details={
                        "fields": [
                            {
                                "loc": ["body", "expected_assignment_id"],
                                "message": "Required for reassignment",
                                "type": "missing",
                            },
                            {
                                "loc": ["body", "expected_assignment_version"],
                                "message": "Required for reassignment",
                                "type": "missing",
                            },
                        ]
                    },
                )
            if (
                active_assignment.id != dispatch_in.expected_assignment_id
                or active_assignment.version
                != dispatch_in.expected_assignment_version
            ):
                raise APIError(
                    status_code=409,
                    code="STALE_VERSION",
                    message="The assignment has changed. Reload and try again.",
                    details={
                        "assignment_id": str(active_assignment.id),
                        "expected_assignment_version": (
                            dispatch_in.expected_assignment_version
                        ),
                        "actual_assignment_version": active_assignment.version,
                    },
                )

        candidates = (
            prefetched_candidates
            if prefetched_candidates is not None
            else read_dispatch_candidates(session=session, ticket_id=ticket.id)
        )
        if prefetched_decision is not None:
            decision = prefetched_decision
        else:
            candidate_data = tuple(
                DispatchCandidateData(
                    handler_id=item.handler_id,
                    open_ticket_count=item.open_ticket_count,
                    last_assigned_at=item.last_assigned_at,
                )
                for item in candidates.items
            )
            if dispatch_in.mode == "MANUAL":
                decision = ManualDispatchStrategy().choose(
                    dispatch_in.handler_id,
                    candidate_data,
                )
            else:
                decision = LeastOpenTicketStrategy().choose(candidate_data)

        selected = (
            next(
                (
                    item
                    for item in candidates.items
                    if item.handler_id == decision.selected_handler_id
                ),
                None,
            )
            if decision.selected_handler_id is not None
            else None
        )
        if selected is None:
            if dispatch_in.mode == "AUTO":
                failure_ticket_id = str(ticket.id)
                failure_ticket_status = ticket.status
                failure_ticket_version = ticket.version
                failure_candidate_count = candidates.candidate_count
                session.add(
                    AuditLog(
                        actor_user_id=actor.user_id,
                        actor_type="USER",
                        action="AUTO_ASSIGN_FAILED",
                        entity_type="TICKET",
                        entity_id=ticket.id,
                        ticket_id=ticket.id,
                        before_state={
                            "status": failure_ticket_status,
                            "version": failure_ticket_version,
                        },
                        after_state={
                            "status": failure_ticket_status,
                            "version": failure_ticket_version,
                        },
                        outcome="FAILED",
                        error_code="NO_ELIGIBLE_HANDLER",
                        request_id=uuid.UUID(actor.request_id),
                        idempotency_key=idempotency_key,
                        detail={
                            "changed_fields": [],
                            "previous_status": failure_ticket_status,
                            "next_status": failure_ticket_status,
                            "strategy_code": decision.strategy_code,
                            "strategy_version": decision.strategy_version,
                            "candidate_count": failure_candidate_count,
                        },
                    )
                )
                session.flush()
                transaction.commit()
            else:
                failure_ticket_id = str(ticket.id)
                failure_candidate_count = candidates.candidate_count
            raise APIError(
                status_code=409,
                code=(
                    "NO_ELIGIBLE_HANDLER"
                    if dispatch_in.mode == "AUTO"
                    else "HANDLER_NOT_ELIGIBLE"
                ),
                message=(
                    "No eligible handler is available for this team."
                    if dispatch_in.mode == "AUTO"
                    else "The selected handler is not eligible for this ticket."
                ),
                details={
                    "ticket_id": failure_ticket_id,
                    "candidate_count": failure_candidate_count,
                    "assignment_changed": False,
                },
            )
        if (
            active_assignment is not None
            and active_assignment.handler_id == selected.handler_id
        ):
            raise APIError(
                status_code=409,
                code="DUPLICATE_ASSIGNMENT",
                message="The selected handler already owns this assignment.",
                details={
                    "ticket_id": str(ticket.id),
                    "assignment_id": str(active_assignment.id),
                },
            )

        now = get_datetime_utc()
        before_state = {"status": ticket.status, "version": ticket.version}
        if active_assignment is not None:
            active_assignment.status = "SUPERSEDED"
            active_assignment.reason = dispatch_in.reason
            active_assignment.version += 1
            session.add(active_assignment)
            session.flush()
            superseded_assignment_id = active_assignment.id
            session.add(
                AuditLog(
                    actor_user_id=actor.user_id,
                    actor_type="USER",
                    action="ASSIGNMENT_SUPERSEDED",
                    entity_type="ASSIGNMENT",
                    entity_id=active_assignment.id,
                    ticket_id=ticket.id,
                    before_state=before_state,
                    after_state={
                        "status": "ASSIGNED",
                        "version": ticket.version + 1,
                    },
                    outcome="SUCCESS",
                    request_id=uuid.UUID(actor.request_id),
                    idempotency_key=idempotency_key,
                    detail={
                        "changed_fields": ["assignment_status", "reason"],
                        "previous_status": before_state["status"],
                        "next_status": "ASSIGNED",
                        "note": dispatch_in.reason,
                    },
                )
            )

        assignment = Assignment(
            ticket_id=ticket.id,
            handler_id=selected.handler_id,
            assigned_by_id=actor.user_id,
            status="ASSIGNED",
            dispatch_mode=dispatch_in.mode,
            strategy_code=decision.strategy_code,
            strategy_version=decision.strategy_version,
            selection_summary={
                "candidate_count": candidates.candidate_count,
                "selected_handler_id": str(selected.handler_id),
                "selected_open_ticket_count": selected.open_ticket_count,
            },
            assigned_at=now,
        )
        session.add(assignment)
        ticket.status = "ASSIGNED"
        ticket.version += 1
        ticket.updated_at = now
        session.add(ticket)

        membership = session.exec(
            select(TeamMembership)
            .where(
                col(TeamMembership.team_id) == ticket.team_id,
                col(TeamMembership.user_id) == selected.handler_id,
            )
            .with_for_update()
        ).one()
        membership.last_assigned_at = now
        session.add(membership)
        session.flush()

        session.add(
            Notification(
                recipient_id=selected.handler_id,
                ticket_id=ticket.id,
                assignment_id=assignment.id,
                notification_type="ASSIGNMENT_RECEIVED",
                payload={
                    "title": "你收到一个新工单",
                    "message": f"工单“{ticket.title}”已派发给你。",
                },
                created_at=now,
            )
        )
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="ASSIGNMENT_CREATED",
                entity_type="ASSIGNMENT",
                entity_id=assignment.id,
                ticket_id=ticket.id,
                before_state=before_state,
                after_state={"status": ticket.status, "version": ticket.version},
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={
                    "changed_fields": ["status", "active_assignment"],
                    "previous_status": before_state["status"],
                    "next_status": ticket.status,
                    "strategy_code": decision.strategy_code,
                    "strategy_version": decision.strategy_version,
                    "candidate_count": candidates.candidate_count,
                    "selected_handler_id": str(selected.handler_id),
                },
            )
        )

        assignment_public = _assignment_public(session=session, assignment=assignment)
        explanation = DispatchExplanation(
            candidate_count=candidates.candidate_count,
            selected_handler_id=selected.handler_id,
            selected_open_ticket_count=selected.open_ticket_count,
            ranked_candidates=[
                CandidateRankingEntry(
                    rank=rank,
                    handler_id=item.handler_id,
                    open_ticket_count=item.open_ticket_count,
                    last_assigned_at=item.last_assigned_at,
                    selected=item.handler_id == selected.handler_id,
                )
                for rank, item in enumerate(decision.ranked_candidates, start=1)
            ],
        )
        result = DispatchResponse(
            ticket=_ticket_state(ticket),
            assignment=assignment_public,
            superseded_assignment_id=superseded_assignment_id,
            explanation=explanation,
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="DISPATCH_TICKET",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=201,
            response_body=response_body,
            resource_type="ASSIGNMENT",
            resource_id=assignment.id,
        )
        return result


def _lock_ticket_and_assignment(
    *,
    session: Session,
    actor: ActorContext,
    assignment_id: uuid.UUID,
) -> tuple[Ticket, Assignment]:
    assignment_ref = session.get(Assignment, assignment_id)
    if assignment_ref is None:
        raise APIError(
            status_code=404,
            code="ASSIGNMENT_NOT_FOUND",
            message="The assignment does not exist.",
        )
    ticket_ref = session.get(Ticket, assignment_ref.ticket_id)
    if ticket_ref is None:
        raise APIError(
            status_code=404,
            code="ASSIGNMENT_NOT_FOUND",
            message="The assignment does not exist.",
        )

    session.exec(
        select(func.pg_advisory_xact_lock(_team_lock_id(ticket_ref.team_id)))
    ).one()
    ticket = session.exec(
        select(Ticket)
        .where(col(Ticket.id) == ticket_ref.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    visible_ticket = session.exec(
        select(Ticket.id).where(
            col(Ticket.id) == ticket.id,
            ticket_visibility_condition(actor),
        )
    ).first()
    if visible_ticket is None:
        raise APIError(
            status_code=404,
            code="ASSIGNMENT_NOT_FOUND",
            message="The assignment does not exist.",
        )
    assignment = session.exec(
        select(Assignment)
        .where(col(Assignment.id) == assignment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if assignment.handler_id != actor.user_id:
        raise APIError(
            status_code=403,
            code="NOT_CURRENT_ASSIGNEE",
            message="Only the current assignee can perform this action.",
            details={"assignment_id": str(assignment.id)},
        )
    return ticket, assignment


def accept_assignment(
    *,
    session: Session,
    actor: ActorContext,
    assignment_id: uuid.UUID,
    idempotency_key: str,
    accept_in: AcceptAssignmentRequest,
) -> TicketMutationResponse:
    """当前 Handler 接受派发，Ticket 与 Assignment 在同一事务推进。"""

    payload = {
        "assignment_id": str(assignment_id),
        **accept_in.model_dump(mode="json"),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="ACCEPT_ASSIGNMENT",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TicketMutationResponse.model_validate(reservation.replay.body)

        ticket, assignment = _lock_ticket_and_assignment(
            session=session,
            actor=actor,
            assignment_id=assignment_id,
        )
        if assignment.status == "SUPERSEDED":
            raise APIError(
                status_code=409,
                code="ASSIGNMENT_SUPERSEDED",
                message="The assignment has been superseded.",
                details={"assignment_id": str(assignment.id)},
            )
        if ticket.version != accept_in.expected_ticket_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "expected_ticket_version": accept_in.expected_ticket_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if assignment.version != accept_in.expected_assignment_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The assignment has changed. Reload and try again.",
                details={
                    "expected_assignment_version": (
                        accept_in.expected_assignment_version
                    ),
                    "actual_assignment_version": assignment.version,
                },
            )
        if ticket.status != "ASSIGNED" or assignment.status != "ASSIGNED":
            raise APIError(
                status_code=409,
                code="INVALID_TRANSITION",
                message="The assignment cannot be accepted in its current state.",
                details={
                    "ticket_id": str(ticket.id),
                    "assignment_id": str(assignment.id),
                    "ticket_status": ticket.status,
                },
            )

        now = get_datetime_utc()
        before_state = {"status": ticket.status, "version": ticket.version}
        assignment.status = "ACCEPTED"
        assignment.responded_at = now
        assignment.version += 1
        ticket.status = "IN_PROGRESS"
        ticket.version += 1
        ticket.updated_at = now
        session.add(assignment)
        session.add(ticket)
        session.flush()

        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="ASSIGNMENT_ACCEPTED",
                entity_type="ASSIGNMENT",
                entity_id=assignment.id,
                ticket_id=ticket.id,
                before_state=before_state,
                after_state={"status": ticket.status, "version": ticket.version},
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={
                    "changed_fields": ["status"],
                    "previous_status": before_state["status"],
                    "next_status": ticket.status,
                },
            )
        )
        result = TicketMutationResponse(
            ticket=_ticket_state(ticket),
            changed_assignment=_assignment_public(
                session=session,
                assignment=assignment,
            ),
            superseded_assignment_id=None,
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="ACCEPT_ASSIGNMENT",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="ASSIGNMENT",
            resource_id=assignment.id,
        )
        return result


def complete_assignment(
    *,
    session: Session,
    actor: ActorContext,
    assignment_id: uuid.UUID,
    idempotency_key: str,
    complete_in: CompleteAssignmentRequest,
) -> TicketMutationResponse:
    """Handler 完成后进入待提交人确认，保留完成说明与完成时间。"""

    payload = {
        "assignment_id": str(assignment_id),
        **complete_in.model_dump(mode="json"),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="COMPLETE_ASSIGNMENT",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TicketMutationResponse.model_validate(reservation.replay.body)

        ticket, assignment = _lock_ticket_and_assignment(
            session=session,
            actor=actor,
            assignment_id=assignment_id,
        )
        if assignment.status == "SUPERSEDED":
            raise APIError(
                status_code=409,
                code="ASSIGNMENT_SUPERSEDED",
                message="The assignment has been superseded.",
                details={"assignment_id": str(assignment.id)},
            )
        if ticket.version != complete_in.expected_ticket_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "expected_ticket_version": complete_in.expected_ticket_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if assignment.version != complete_in.expected_assignment_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The assignment has changed. Reload and try again.",
                details={
                    "expected_assignment_version": (
                        complete_in.expected_assignment_version
                    ),
                    "actual_assignment_version": assignment.version,
                },
            )
        if ticket.status != "IN_PROGRESS" or assignment.status != "ACCEPTED":
            raise APIError(
                status_code=409,
                code="INVALID_TRANSITION",
                message="The assignment cannot be completed in its current state.",
                details={
                    "ticket_id": str(ticket.id),
                    "assignment_id": str(assignment.id),
                    "ticket_status": ticket.status,
                },
            )

        now = get_datetime_utc()
        before_state = {"status": ticket.status, "version": ticket.version}
        assignment.status = "COMPLETED"
        assignment.completion_note = complete_in.completion_note
        assignment.finished_at = now
        assignment.version += 1
        ticket.status = "PENDING_CONFIRMATION"
        ticket.version += 1
        ticket.updated_at = now
        session.add(assignment)
        session.add(ticket)
        session.flush()

        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="ASSIGNMENT_COMPLETED",
                entity_type="ASSIGNMENT",
                entity_id=assignment.id,
                ticket_id=ticket.id,
                before_state=before_state,
                after_state={"status": ticket.status, "version": ticket.version},
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={
                    "changed_fields": ["status", "completion_note"],
                    "previous_status": before_state["status"],
                    "next_status": ticket.status,
                    "note": "completion_recorded",
                },
            )
        )
        result = TicketMutationResponse(
            ticket=_ticket_state(ticket),
            changed_assignment=_assignment_public(
                session=session,
                assignment=assignment,
            ),
            superseded_assignment_id=None,
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="COMPLETE_ASSIGNMENT",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="ASSIGNMENT",
            resource_id=assignment.id,
        )
        return result


def reject_assignment(
    *,
    session: Session,
    actor: ActorContext,
    assignment_id: uuid.UUID,
    idempotency_key: str,
    reject_in: RejectAssignmentRequest,
) -> TicketMutationResponse:
    """当前 Handler 拒绝派发；Ticket 回到待派发并释放活动 Assignment。"""

    payload = {
        "assignment_id": str(assignment_id),
        **reject_in.model_dump(mode="json"),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REJECT_ASSIGNMENT",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TicketMutationResponse.model_validate(reservation.replay.body)

        ticket, assignment = _lock_ticket_and_assignment(
            session=session,
            actor=actor,
            assignment_id=assignment_id,
        )
        if assignment.status == "SUPERSEDED":
            raise APIError(
                status_code=409,
                code="ASSIGNMENT_SUPERSEDED",
                message="The assignment has been superseded.",
                details={"assignment_id": str(assignment.id)},
            )
        if ticket.version != reject_in.expected_ticket_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "expected_ticket_version": reject_in.expected_ticket_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if assignment.version != reject_in.expected_assignment_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The assignment has changed. Reload and try again.",
                details={
                    "expected_assignment_version": (
                        reject_in.expected_assignment_version
                    ),
                    "actual_assignment_version": assignment.version,
                },
            )
        if ticket.status != "ASSIGNED" or assignment.status != "ASSIGNED":
            raise APIError(
                status_code=409,
                code="INVALID_TRANSITION",
                message="The assignment cannot be rejected in its current state.",
                details={
                    "ticket_id": str(ticket.id),
                    "assignment_id": str(assignment.id),
                    "ticket_status": ticket.status,
                },
            )

        now = get_datetime_utc()
        before_state = {"status": ticket.status, "version": ticket.version}
        assignment.status = "REJECTED"
        assignment.reason = reject_in.reason
        assignment.responded_at = now
        assignment.version += 1
        ticket.status = "PENDING_ASSIGNMENT"
        ticket.version += 1
        ticket.updated_at = now
        session.add(assignment)
        session.add(ticket)
        session.flush()

        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="ASSIGNMENT_REJECTED",
                entity_type="ASSIGNMENT",
                entity_id=assignment.id,
                ticket_id=ticket.id,
                before_state=before_state,
                after_state={"status": ticket.status, "version": ticket.version},
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={
                    "changed_fields": ["status", "reason"],
                    "previous_status": before_state["status"],
                    "next_status": ticket.status,
                    "note": reject_in.reason,
                },
            )
        )
        result = TicketMutationResponse(
            ticket=_ticket_state(ticket),
            changed_assignment=_assignment_public(
                session=session,
                assignment=assignment,
            ),
            superseded_assignment_id=None,
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REJECT_ASSIGNMENT",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="ASSIGNMENT",
            resource_id=assignment.id,
        )
        return result


def _lock_visible_ticket_for_action(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
) -> Ticket:
    ticket_ref = session.get(Ticket, ticket_id)
    if ticket_ref is None:
        raise APIError(
            status_code=404,
            code="TICKET_NOT_FOUND",
            message="The ticket does not exist.",
        )
    session.exec(
        select(func.pg_advisory_xact_lock(_team_lock_id(ticket_ref.team_id)))
    ).one()
    ticket = session.exec(
        select(Ticket)
        .where(col(Ticket.id) == ticket_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    visible = session.exec(
        select(Ticket.id).where(
            col(Ticket.id) == ticket.id,
            ticket_visibility_condition(actor),
        )
    ).first()
    if visible is None:
        raise APIError(
            status_code=404,
            code="TICKET_NOT_FOUND",
            message="The ticket does not exist.",
        )
    return ticket


def close_ticket(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    idempotency_key: str,
    close_in: CloseTicketRequest,
) -> TicketMutationResponse:
    """提交人或管理角色关闭待确认工单；评论与关闭共享同一 Ticket 行锁。"""

    payload = {
        "ticket_id": str(ticket_id),
        **close_in.model_dump(mode="json"),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CLOSE_TICKET",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TicketMutationResponse.model_validate(reservation.replay.body)

        ticket = _lock_visible_ticket_for_action(
            session=session,
            actor=actor,
            ticket_id=ticket_id,
        )
        if (
            ticket.submitter_id != actor.user_id
            and not actor.has_any_role(("DISPATCHER", "ADMIN"))
        ):
            raise APIError(
                status_code=403,
                code="ACTION_FORBIDDEN",
                message="The ticket cannot be closed by this user.",
                details={"ticket_id": str(ticket.id)},
            )
        if ticket.version != close_in.expected_ticket_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "expected_ticket_version": close_in.expected_ticket_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if ticket.status != "PENDING_CONFIRMATION":
            raise APIError(
                status_code=409,
                code="INVALID_TRANSITION",
                message="Only pending-confirmation tickets can be closed.",
                details={
                    "ticket_id": str(ticket.id),
                    "ticket_status": ticket.status,
                },
            )

        before_state = {"status": ticket.status, "version": ticket.version}
        ticket.status = "CLOSED"
        ticket.version += 1
        ticket.updated_at = get_datetime_utc()
        session.add(ticket)
        session.flush()

        detail: dict[str, object] = {
            "changed_fields": ["status"],
            "previous_status": before_state["status"],
            "next_status": ticket.status,
        }
        if close_in.resolution_note is not None:
            detail["note"] = close_in.resolution_note
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="TICKET_CLOSED",
                entity_type="TICKET",
                entity_id=ticket.id,
                ticket_id=ticket.id,
                before_state=before_state,
                after_state={"status": ticket.status, "version": ticket.version},
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail=detail,
            )
        )
        result = TicketMutationResponse(
            ticket=_ticket_state(ticket),
            changed_assignment=None,
            superseded_assignment_id=None,
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CLOSE_TICKET",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="TICKET",
            resource_id=ticket.id,
        )
        return result


def reopen_ticket(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    idempotency_key: str,
    reopen_in: ReopenTicketRequest,
) -> TicketMutationResponse:
    """提交人或管理角色重开已关闭工单，历史 Assignment 保持不可变。"""

    payload = {
        "ticket_id": str(ticket_id),
        **reopen_in.model_dump(mode="json"),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REOPEN_TICKET",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TicketMutationResponse.model_validate(reservation.replay.body)

        ticket = _lock_visible_ticket_for_action(
            session=session,
            actor=actor,
            ticket_id=ticket_id,
        )
        if (
            ticket.submitter_id != actor.user_id
            and not actor.has_any_role(("DISPATCHER", "ADMIN"))
        ):
            raise APIError(
                status_code=403,
                code="ACTION_FORBIDDEN",
                message="The ticket cannot be reopened by this user.",
                details={"ticket_id": str(ticket.id)},
            )
        if ticket.version != reopen_in.expected_ticket_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "expected_ticket_version": reopen_in.expected_ticket_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if ticket.status != "CLOSED":
            raise APIError(
                status_code=409,
                code="INVALID_TRANSITION",
                message="Only closed tickets can be reopened.",
                details={
                    "ticket_id": str(ticket.id),
                    "ticket_status": ticket.status,
                },
            )

        before_state = {"status": ticket.status, "version": ticket.version}
        ticket.status = "PENDING_ASSIGNMENT"
        ticket.version += 1
        ticket.updated_at = get_datetime_utc()
        session.add(ticket)
        session.flush()
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="TICKET_REOPENED",
                entity_type="TICKET",
                entity_id=ticket.id,
                ticket_id=ticket.id,
                before_state=before_state,
                after_state={"status": ticket.status, "version": ticket.version},
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={
                    "changed_fields": ["status", "reason"],
                    "previous_status": before_state["status"],
                    "next_status": ticket.status,
                    "note": reopen_in.reason,
                },
            )
        )
        result = TicketMutationResponse(
            ticket=_ticket_state(ticket),
            changed_assignment=None,
            superseded_assignment_id=None,
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REOPEN_TICKET",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="TICKET",
            resource_id=ticket.id,
        )
        return result
