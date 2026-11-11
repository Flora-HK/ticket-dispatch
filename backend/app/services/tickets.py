import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, and_, exists, or_, true
from sqlmodel import Session, col, select

from app.api.deps import ActorContext
from app.core.errors import APIError
from app.models import (
    Assignment,
    AssignmentPublic,
    AuditLog,
    Comment,
    CommentCreateRequest,
    CommentPage,
    CommentPublic,
    Team,
    TeamSummary,
    Ticket,
    TicketAction,
    TicketCreateRequest,
    TicketDetailPublic,
    TicketPage,
    TicketStatus,
    TicketSummaryPublic,
    TicketUpdateRequest,
    User,
    UserSummary,
    get_datetime_utc,
)
from app.services.idempotency import (
    begin_idempotent_command,
    finish_idempotent_command,
)

type TicketSortField = Literal["updated_at", "created_at"]


@dataclass(frozen=True, slots=True)
class TicketSort:
    field: TicketSortField
    direction: Literal["asc", "desc"]


TICKET_SORTS = {
    "updated_at:desc": TicketSort(field="updated_at", direction="desc"),
    "updated_at:asc": TicketSort(field="updated_at", direction="asc"),
    "created_at:desc": TicketSort(field="created_at", direction="desc"),
    "created_at:asc": TicketSort(field="created_at", direction="asc"),
}


def _rollback_authentication_read(session: Session) -> None:
    """认证依赖已用同一 Session 读角色；业务事务开始前结束该只读事务。"""

    if session.in_transaction():
        session.rollback()


def _request_uuid(actor: ActorContext) -> uuid.UUID:
    return uuid.UUID(actor.request_id)


def _team_summary(team: Team) -> TeamSummary:
    return TeamSummary(id=team.id, name=team.name)


def _user_summary(user: User) -> UserSummary:
    return UserSummary.model_validate(user)


def false_condition() -> ColumnElement[bool]:
    """没有业务角色时返回空可见集，同时保持查询结构一致。"""

    return col(Ticket.id).is_(None)


def ticket_visibility_condition(actor: ActorContext) -> ColumnElement[bool]:
    """把多角色可见范围合成为 SQL 条件，避免先查全表再由 Python 裁剪。"""

    if actor.has_any_role(("DISPATCHER", "ADMIN")):
        return true()

    conditions: list[ColumnElement[bool]] = []
    if "SUBMITTER" in actor.roles:
        conditions.append(col(Ticket.submitter_id) == actor.user_id)
    if "HANDLER" in actor.roles:
        conditions.append(
            exists(
                select(Assignment.id).where(
                    col(Assignment.ticket_id) == col(Ticket.id),
                    col(Assignment.handler_id) == actor.user_id,
                )
            )
        )
    if not conditions:
        return false_condition()
    return or_(*conditions)


def _load_visible_ticket(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    for_update: bool = False,
) -> tuple[Ticket, Team, User]:
    statement = (
        select(Ticket, Team, User)
        .join(Team, col(Ticket.team_id) == col(Team.id))
        .join(User, col(Ticket.submitter_id) == col(User.id))
        .where(
            col(Ticket.id) == ticket_id,
            ticket_visibility_condition(actor),
        )
    )
    if for_update:
        statement = statement.with_for_update(of=Ticket)
    row = session.exec(statement).first()
    if row is None:
        raise APIError(
            status_code=404,
            code="TICKET_NOT_FOUND",
            message="The ticket does not exist.",
        )
    return row[0], row[1], row[2]


def _active_assignment(session: Session, ticket_id: uuid.UUID) -> Assignment | None:
    return session.exec(
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


def _assignment_public(
    *,
    session: Session,
    assignment: Assignment | None,
) -> AssignmentPublic | None:
    if assignment is None:
        return None
    handler = session.get(User, assignment.handler_id)
    assigned_by = session.get(User, assignment.assigned_by_id)
    if handler is None or assigned_by is None:
        raise RuntimeError("assignment user relationship is missing")
    return AssignmentPublic(
        id=assignment.id,
        ticket_id=assignment.ticket_id,
        handler_id=assignment.handler_id,
        handler=_user_summary(handler),
        assigned_by_id=assignment.assigned_by_id,
        assigned_by=_user_summary(assigned_by),
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


def _allowed_actions(
    *,
    actor: ActorContext,
    ticket: Ticket,
    active_assignment: Assignment | None,
) -> list[TicketAction]:
    """按契约顺序返回当前 Actor 在当前状态可执行的动作提示。"""

    actions: list[TicketAction] = []
    is_submitter = ticket.submitter_id == actor.user_id
    can_manage = actor.has_any_role(("DISPATCHER", "ADMIN"))

    if ticket.status == "PENDING_ASSIGNMENT" and (
        is_submitter or "ADMIN" in actor.roles
    ):
        actions.append("EDIT")
    if (
        ticket.status in ("PENDING_ASSIGNMENT", "ASSIGNED", "IN_PROGRESS")
        and can_manage
    ):
        actions.append("DISPATCH")
    if ticket.status != "CLOSED":
        actions.append("COMMENT")

    is_current_handler = (
        active_assignment is not None
        and active_assignment.handler_id == actor.user_id
    )
    if (
        ticket.status == "ASSIGNED"
        and is_current_handler
        and active_assignment is not None
        and active_assignment.status == "ASSIGNED"
    ):
        actions.extend(("ACCEPT", "REJECT"))
    if (
        ticket.status == "IN_PROGRESS"
        and is_current_handler
        and active_assignment is not None
        and active_assignment.status == "ACCEPTED"
    ):
        actions.append("COMPLETE")
    if ticket.status == "PENDING_CONFIRMATION" and (is_submitter or can_manage):
        actions.append("CLOSE")
    if ticket.status == "CLOSED" and (is_submitter or can_manage):
        actions.append("REOPEN")
    return actions


def _ticket_summary(
    *,
    ticket: Ticket,
    team: Team,
    submitter: User,
) -> TicketSummaryPublic:
    return TicketSummaryPublic(
        id=ticket.id,
        team_id=ticket.team_id,
        team=_team_summary(team),
        submitter_id=ticket.submitter_id,
        submitter=_user_summary(submitter),
        title=ticket.title,
        status=cast(TicketStatus, ticket.status),
        version=ticket.version,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _ticket_detail(
    *,
    session: Session,
    actor: ActorContext,
    ticket: Ticket,
    team: Team,
    submitter: User,
) -> TicketDetailPublic:
    active = _active_assignment(session, ticket.id)
    summary = _ticket_summary(ticket=ticket, team=team, submitter=submitter)
    return TicketDetailPublic(
        **summary.model_dump(),
        description=ticket.description,
        active_assignment=_assignment_public(
            session=session,
            assignment=active,
        ),
        allowed_actions=_allowed_actions(
            actor=actor,
            ticket=ticket,
            active_assignment=active,
        ),
    )


def _audit_ticket_write(
    *,
    session: Session,
    actor: ActorContext,
    action: str,
    ticket: Ticket,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    idempotency_key: str,
    changed_fields: list[str],
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor.user_id,
            actor_type="USER",
            action=action,
            entity_type="TICKET",
            entity_id=ticket.id,
            ticket_id=ticket.id,
            before_state=before_state,
            after_state=after_state,
            outcome="SUCCESS",
            request_id=_request_uuid(actor),
            idempotency_key=idempotency_key,
            detail={"changed_fields": changed_fields},
        )
    )


def create_ticket(
    *,
    session: Session,
    actor: ActorContext,
    idempotency_key: str,
    ticket_in: TicketCreateRequest,
) -> TicketDetailPublic:
    """创建待派发 Ticket，并在同一事务写审计和幂等响应。"""

    payload = ticket_in.model_dump(mode="json")
    _rollback_authentication_read(session)
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_TICKET",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TicketDetailPublic.model_validate(reservation.replay.body)

        team = session.get(Team, ticket_in.team_id)
        if team is None or not team.is_active:
            raise APIError(
                status_code=404,
                code="TEAM_NOT_FOUND",
                message="The team does not exist or is inactive.",
            )

        ticket = Ticket(
            team_id=team.id,
            submitter_id=actor.user_id,
            title=ticket_in.title,
            description=ticket_in.description,
            status="PENDING_ASSIGNMENT",
        )
        session.add(ticket)
        session.flush()
        submitter = session.get(User, actor.user_id)
        if submitter is None:
            raise RuntimeError("authenticated user disappeared during create")

        detail = _ticket_detail(
            session=session,
            actor=actor,
            ticket=ticket,
            team=team,
            submitter=submitter,
        )
        response_body = detail.model_dump(mode="json")
        _audit_ticket_write(
            session=session,
            actor=actor,
            action="TICKET_CREATED",
            ticket=ticket,
            before_state=None,
            after_state={
                "status": ticket.status,
                "version": ticket.version,
            },
            idempotency_key=idempotency_key,
            changed_fields=["team_id", "title", "description", "status"],
        )
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_TICKET",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=201,
            response_body=response_body,
            resource_type="TICKET",
            resource_id=ticket.id,
        )
        return detail


def _parse_sort(sort: str) -> TicketSort:
    parsed = TICKET_SORTS.get(sort)
    if parsed is None:
        raise APIError(
            status_code=422,
            code="INVALID_SORT",
            message="The requested ticket sort is not supported.",
        )
    return parsed


def _ensure_utc(value: datetime | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message=f"{field_name} must use UTC.",
        )
    return value.astimezone(UTC)


def _cursor_payload(
    *,
    sort_name: str,
    filters: dict[str, Any],
    value: datetime,
    row_id: uuid.UUID,
) -> str:
    payload = json.dumps(
        {
            "sort": sort_name,
            "filters": filters,
            "value": value.isoformat(),
            "id": str(row_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(
    *,
    cursor: str,
    sort_name: str,
    filters: dict[str, Any],
) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if payload["sort"] != sort_name or payload["filters"] != filters:
            raise ValueError("cursor is bound to another query")
        value = datetime.fromisoformat(payload["value"])
        if value.tzinfo is None:
            raise ValueError("cursor timestamp has no timezone")
        return value, uuid.UUID(payload["id"])
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


def read_ticket_page(
    *,
    session: Session,
    actor: ActorContext,
    team_id: uuid.UUID | None,
    status: str | None,
    submitter_id: uuid.UUID | None,
    assigned_to_me: bool,
    created_from: datetime | None,
    created_to: datetime | None,
    cursor: str | None,
    limit: int,
    sort: str,
) -> TicketPage:
    """在 SQL 中组合可见范围、筛选和键集分页，避免凭详情接口枚举资源。"""

    sort_spec = _parse_sort(sort)
    if status is not None and status not in {
        "PENDING_ASSIGNMENT",
        "ASSIGNED",
        "IN_PROGRESS",
        "PENDING_CONFIRMATION",
        "CLOSED",
    }:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The ticket status filter is invalid.",
        )
    if submitter_id is not None and not actor.has_any_role(
        ("DISPATCHER", "ADMIN")
    ):
        raise APIError(
            status_code=403,
            code="ACTION_FORBIDDEN",
            message="Only dispatchers and administrators can filter by submitter.",
        )
    created_from = _ensure_utc(created_from, field_name="created_from")
    created_to = _ensure_utc(created_to, field_name="created_to")

    filters = {
        "team_id": str(team_id) if team_id else None,
        "status": status,
        "submitter_id": str(submitter_id) if submitter_id else None,
        "assigned_to_me": assigned_to_me,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
    }
    statement = (
        select(Ticket, Team, User)
        .join(Team, col(Ticket.team_id) == col(Team.id))
        .join(User, col(Ticket.submitter_id) == col(User.id))
        .where(ticket_visibility_condition(actor))
    )
    if team_id is not None:
        statement = statement.where(col(Ticket.team_id) == team_id)
    if status is not None:
        statement = statement.where(col(Ticket.status) == status)
    if submitter_id is not None:
        statement = statement.where(col(Ticket.submitter_id) == submitter_id)
    if assigned_to_me:
        statement = statement.where(
            exists(
                select(Assignment.id).where(
                    col(Assignment.ticket_id) == col(Ticket.id),
                    col(Assignment.handler_id) == actor.user_id,
                )
            )
        )
    if created_from is not None:
        statement = statement.where(col(Ticket.created_at) >= created_from)
    if created_to is not None:
        statement = statement.where(col(Ticket.created_at) < created_to)

    value_column = (
        col(Ticket.updated_at)
        if sort_spec.field == "updated_at"
        else col(Ticket.created_at)
    )
    if cursor is not None:
        cursor_value, cursor_id = _decode_cursor(
            cursor=cursor,
            sort_name=sort,
            filters=filters,
        )
        if sort_spec.direction == "desc":
            statement = statement.where(
                or_(
                    value_column < cursor_value,
                    and_(
                        value_column == cursor_value,
                        col(Ticket.id) < cursor_id,
                    ),
                )
            )
        else:
            statement = statement.where(
                or_(
                    value_column > cursor_value,
                    and_(
                        value_column == cursor_value,
                        col(Ticket.id) > cursor_id,
                    ),
                )
            )

    order = (
        value_column.desc()
        if sort_spec.direction == "desc"
        else value_column.asc()
    )
    id_order = (
        col(Ticket.id).desc()
        if sort_spec.direction == "desc"
        else col(Ticket.id).asc()
    )
    statement = statement.order_by(order, id_order).limit(limit + 1)
    rows = list(session.exec(statement).all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [
        _ticket_summary(ticket=ticket, team=team, submitter=submitter)
        for ticket, team, submitter in page_rows
    ]
    next_cursor = None
    if has_more and page_rows:
        last_ticket = page_rows[-1][0]
        last_value = (
            last_ticket.updated_at
            if sort_spec.field == "updated_at"
            else last_ticket.created_at
        )
        next_cursor = _cursor_payload(
            sort_name=sort,
            filters=filters,
            value=last_value,
            row_id=last_ticket.id,
        )
    return TicketPage(items=items, next_cursor=next_cursor)


def read_ticket_detail(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
) -> TicketDetailPublic:
    ticket, team, submitter = _load_visible_ticket(
        session=session,
        actor=actor,
        ticket_id=ticket_id,
    )
    return _ticket_detail(
        session=session,
        actor=actor,
        ticket=ticket,
        team=team,
        submitter=submitter,
    )


def update_ticket(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    idempotency_key: str,
    ticket_in: TicketUpdateRequest,
) -> TicketDetailPublic:
    """仅允许创建人或 Admin 修改待派发正文，并用版本和事务阻止覆盖。"""

    payload = {
        "ticket_id": str(ticket_id),
        **ticket_in.model_dump(mode="json", exclude_unset=True),
    }
    _rollback_authentication_read(session)
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPDATE_TICKET",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TicketDetailPublic.model_validate(reservation.replay.body)

        ticket, team, submitter = _load_visible_ticket(
            session=session,
            actor=actor,
            ticket_id=ticket_id,
            for_update=True,
        )
        if ticket.submitter_id != actor.user_id and "ADMIN" not in actor.roles:
            raise APIError(
                status_code=403,
                code="ACTION_FORBIDDEN",
                message="Only the submitter or an administrator can edit this ticket.",
            )
        if ticket.version != ticket_in.expected_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "ticket_id": str(ticket.id),
                    "expected_ticket_version": ticket_in.expected_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if ticket.status != "PENDING_ASSIGNMENT":
            raise APIError(
                status_code=409,
                code="INVALID_TRANSITION",
                message="Only pending tickets can be edited.",
                details={
                    "ticket_id": str(ticket.id),
                    "ticket_status": ticket.status,
                },
            )

        before_state = {
            "status": ticket.status,
            "version": ticket.version,
        }
        changed_fields = [
            field
            for field in ("title", "description")
            if getattr(ticket_in, field) is not None
        ]
        updates = ticket_in.model_dump(
            exclude={"expected_version"},
            exclude_none=True,
        )
        ticket.sqlmodel_update(updates)
        ticket.version += 1
        ticket.updated_at = get_datetime_utc()
        session.add(ticket)
        session.flush()

        detail = _ticket_detail(
            session=session,
            actor=actor,
            ticket=ticket,
            team=team,
            submitter=submitter,
        )
        response_body = detail.model_dump(mode="json")
        _audit_ticket_write(
            session=session,
            actor=actor,
            action="TICKET_UPDATED",
            ticket=ticket,
            before_state=before_state,
            after_state={
                "status": ticket.status,
                "version": ticket.version,
            },
            idempotency_key=idempotency_key,
            changed_fields=changed_fields,
        )
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPDATE_TICKET",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="TICKET",
            resource_id=ticket.id,
        )
        return detail


def _comment_public(*, comment: Comment, author: User) -> CommentPublic:
    return CommentPublic(
        id=comment.id,
        ticket_id=comment.ticket_id,
        author=_user_summary(author),
        body=comment.body,
        created_at=comment.created_at,
    )


def read_comments(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    cursor: str | None,
    limit: int,
) -> CommentPage:
    """评论时间线按创建时间和 UUID 稳定升序，先验证 Ticket 可见性。"""

    _load_visible_ticket(
        session=session,
        actor=actor,
        ticket_id=ticket_id,
    )
    filters = {"ticket_id": str(ticket_id)}
    statement = (
        select(Comment, User)
        .join(User, col(Comment.author_id) == col(User.id))
        .where(col(Comment.ticket_id) == ticket_id)
    )
    if cursor is not None:
        created_at, comment_id = _decode_cursor(
            cursor=cursor,
            sort_name="created_at:asc",
            filters=filters,
        )
        statement = statement.where(
            or_(
                col(Comment.created_at) > created_at,
                and_(
                    col(Comment.created_at) == created_at,
                    col(Comment.id) > comment_id,
                ),
            )
        )
    statement = statement.order_by(
        col(Comment.created_at).asc(),
        col(Comment.id).asc(),
    ).limit(limit + 1)
    rows = list(session.exec(statement).all())
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [
        _comment_public(comment=comment, author=author)
        for comment, author in page_rows
    ]
    next_cursor = None
    if has_more and page_rows:
        last_comment = page_rows[-1][0]
        next_cursor = _cursor_payload(
            sort_name="created_at:asc",
            filters=filters,
            value=last_comment.created_at,
            row_id=last_comment.id,
        )
    return CommentPage(items=items, next_cursor=next_cursor)


def create_comment(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    idempotency_key: str,
    comment_in: CommentCreateRequest,
) -> CommentPublic:
    """锁 Ticket 后重新校验可见性、版本和关闭状态，再写评论与审计。"""

    payload = {
        "ticket_id": str(ticket_id),
        **comment_in.model_dump(mode="json"),
    }
    _rollback_authentication_read(session)
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_COMMENT",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return CommentPublic.model_validate(reservation.replay.body)

        ticket, _team, _submitter = _load_visible_ticket(
            session=session,
            actor=actor,
            ticket_id=ticket_id,
            for_update=True,
        )
        if ticket.version != comment_in.expected_ticket_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The ticket has changed. Reload and try again.",
                details={
                    "ticket_id": str(ticket.id),
                    "expected_ticket_version": comment_in.expected_ticket_version,
                    "actual_ticket_version": ticket.version,
                },
            )
        if ticket.status == "CLOSED":
            raise APIError(
                status_code=409,
                code="TICKET_CLOSED",
                message="Closed tickets cannot receive comments.",
                details={
                    "ticket_id": str(ticket.id),
                    "ticket_status": "CLOSED",
                },
            )

        before_state = {
            "status": ticket.status,
            "version": ticket.version,
        }
        comment = Comment(
            ticket_id=ticket.id,
            author_id=actor.user_id,
            body=comment_in.body,
        )
        session.add(comment)
        ticket.version += 1
        ticket.updated_at = get_datetime_utc()
        session.add(ticket)
        session.flush()

        author = session.get(User, actor.user_id)
        if author is None:
            raise RuntimeError("authenticated user disappeared during comment")
        result = _comment_public(comment=comment, author=author)
        response_body = result.model_dump(mode="json")
        _audit_ticket_write(
            session=session,
            actor=actor,
            action="COMMENT_CREATED",
            ticket=ticket,
            before_state=before_state,
            after_state={
                "status": ticket.status,
                "version": ticket.version,
            },
            idempotency_key=idempotency_key,
            changed_fields=["comments"],
        )
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_COMMENT",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=201,
            response_body=response_body,
            resource_type="COMMENT",
            resource_id=comment.id,
        )
        return result
