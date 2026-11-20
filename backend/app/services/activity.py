import base64
import binascii
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, and_, or_
from sqlmodel import Session, col, select

from app.api.deps import ActorContext
from app.core.errors import APIError
from app.models import (
    ASSIGNMENT_STRATEGY_CODES,
    AUDIT_ACTIONS,
    AUDIT_ACTOR_TYPES,
    AUDIT_ENTITY_TYPES,
    AUDIT_OUTCOMES,
    NOTIFICATION_TYPES,
    ROLE_CODES,
    TICKET_STATUSES,
    TIMELINE_EVENT_TYPES,
    Assignment,
    AuditAction,
    AuditActorType,
    AuditDetail,
    AuditEntityType,
    AuditLog,
    AuditLogPage,
    AuditLogPublic,
    AuditOutcome,
    Notification,
    NotificationPage,
    NotificationPublic,
    RoleCode,
    StateSnapshot,
    Ticket,
    TicketStatus,
    TimelineEventPage,
    TimelineEventPublic,
    TimelineEventType,
    TimelineMetadata,
    User,
    UserSummary,
)
from app.services.tickets import ticket_visibility_condition

type SortDirection = Literal["asc", "desc"]


def _invalid_cursor() -> APIError:
    return APIError(
        status_code=422,
        code="INVALID_CURSOR",
        message="The cursor is invalid for this query.",
    )


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


def _parse_sort(
    *,
    sort: str,
    allowed: dict[str, SortDirection],
) -> SortDirection:
    direction = allowed.get(sort)
    if direction is None:
        raise APIError(
            status_code=422,
            code="INVALID_SORT",
            message="The requested sort is not supported.",
        )
    return direction


def _parse_entity_key(value: str | None) -> dict[str, str] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="entity_key must be a JSON object of string values.",
        ) from exc
    if (
        not isinstance(parsed, dict)
        or not parsed
        or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in parsed.items()
        )
    ):
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="entity_key must be a JSON object of string values.",
        )
    return parsed


def _cursor_payload(
    *,
    resource: str,
    sort_name: str,
    filters: dict[str, Any],
    value: datetime,
    row_id: object,
) -> str:
    payload = json.dumps(
        {
            "resource": resource,
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
    resource: str,
    sort_name: str,
    filters: dict[str, Any],
) -> tuple[datetime, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if (
            payload["resource"] != resource
            or payload["sort"] != sort_name
            or payload["filters"] != filters
        ):
            raise ValueError("cursor is bound to another query")
        value = datetime.fromisoformat(payload["value"])
        if value.tzinfo is None:
            raise ValueError("cursor timestamp has no timezone")
        row_id = payload["id"]
        if not isinstance(row_id, str):
            raise TypeError("cursor id is not a string")
        return value, row_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise _invalid_cursor() from exc


def _visible_ticket_condition(
    *,
    actor: ActorContext,
    ticket_id: uuid.UUID,
) -> list[ColumnElement[bool]]:
    return [
        col(Ticket.id) == ticket_id,
        ticket_visibility_condition(actor),
    ]


def _ensure_ticket_visible(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
) -> None:
    visible = session.exec(
        select(Ticket.id).where(
            *_visible_ticket_condition(actor=actor, ticket_id=ticket_id)
        )
    ).first()
    if visible is None:
        raise APIError(
            status_code=404,
            code="TICKET_NOT_FOUND",
            message="The ticket does not exist.",
        )


def _ticket_status(value: object) -> TicketStatus | None:
    if isinstance(value, str) and value in TICKET_STATUSES:
        return value
    return None


def _state_snapshot(value: object) -> StateSnapshot | None:
    if not isinstance(value, dict):
        return None
    status = _ticket_status(value.get("status"))
    version = value.get("version")
    if status is None or not isinstance(version, int):
        return None
    return StateSnapshot.model_validate({"status": status, "version": version})


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _audit_detail(value: object) -> AuditDetail:
    """逐字段构造公开详情，JSONB 中任何非契约字段都在边界处丢弃。"""

    if not isinstance(value, dict):
        return AuditDetail()
    changed_fields = value.get("changed_fields")
    role_codes = value.get("role_codes")
    strategy_code = value.get("strategy_code")
    strategy_version = value.get("strategy_version")
    candidate_count = value.get("candidate_count")
    note = value.get("note")
    return AuditDetail(
        changed_fields=(
            [item for item in changed_fields if isinstance(item, str)]
            if isinstance(changed_fields, list)
            else None
        ),
        previous_status=_ticket_status(value.get("previous_status")),
        next_status=_ticket_status(value.get("next_status")),
        strategy_code=(
            strategy_code
            if isinstance(strategy_code, str)
            and strategy_code in ASSIGNMENT_STRATEGY_CODES
            else None
        ),
        strategy_version=(
            strategy_version if isinstance(strategy_version, str) else None
        ),
        candidate_count=(
            candidate_count if isinstance(candidate_count, int) else None
        ),
        selected_handler_id=_uuid_or_none(value.get("selected_handler_id")),
        role_codes=cast(
            list[RoleCode],
            [
                item
                for item in role_codes
                if isinstance(item, str) and item in ROLE_CODES
            ],
        )
        if isinstance(role_codes, list)
        else None,
        note=note if isinstance(note, str) else None,
    )


def _actor_summary(session: Session, actor_user_id: uuid.UUID | None) -> UserSummary | None:
    if actor_user_id is None:
        return None
    actor = session.get(User, actor_user_id)
    return UserSummary.model_validate(actor) if actor is not None else None


def _audit_public(session: Session, audit: AuditLog) -> AuditLogPublic:
    if audit.id is None:
        raise RuntimeError("persisted audit row has no identity")
    actor_type: AuditActorType | None = (
        audit.actor_type if audit.actor_type in AUDIT_ACTOR_TYPES else None
    )
    action: AuditAction | None = (
        audit.action if audit.action in AUDIT_ACTIONS else None
    )
    entity_type: AuditEntityType | None = (
        audit.entity_type if audit.entity_type in AUDIT_ENTITY_TYPES else None
    )
    outcome: AuditOutcome | None = (
        audit.outcome if audit.outcome in AUDIT_OUTCOMES else None
    )
    if actor_type is None or action is None or entity_type is None or outcome is None:
        raise RuntimeError("persisted audit row violates a public whitelist")
    return AuditLogPublic(
        id=audit.id,
        actor=_actor_summary(session, audit.actor_user_id),
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=audit.entity_id,
        entity_key=audit.entity_key,
        ticket_id=audit.ticket_id,
        before_state=_state_snapshot(audit.before_state),
        after_state=_state_snapshot(audit.after_state),
        outcome=outcome,
        error_code=audit.error_code,
        request_id=audit.request_id,
        created_at=audit.created_at,
        detail=_audit_detail(audit.detail),
    )


def _timeline_metadata(session: Session, audit: AuditLog) -> TimelineMetadata:
    detail = audit.detail if isinstance(audit.detail, dict) else {}
    assignment_id = (
        audit.entity_id
        if audit.entity_type == "ASSIGNMENT" and audit.entity_id is not None
        else None
    )
    handler_id = _uuid_or_none(detail.get("selected_handler_id"))
    if handler_id is None and assignment_id is not None:
        assignment = session.get(Assignment, assignment_id)
        handler_id = assignment.handler_id if assignment is not None else None
    strategy_code = detail.get("strategy_code")
    note = detail.get("note")
    return TimelineMetadata(
        previous_status=_ticket_status(
            detail.get("previous_status")
            or (audit.before_state or {}).get("status")
        ),
        next_status=_ticket_status(
            detail.get("next_status") or (audit.after_state or {}).get("status")
        ),
        assignment_id=assignment_id,
        handler_id=handler_id,
        strategy_code=(
            strategy_code
            if isinstance(strategy_code, str)
            and strategy_code in ASSIGNMENT_STRATEGY_CODES
            else None
        ),
        note=note if isinstance(note, str) else None,
    )


_TIMELINE_SUMMARIES = {
    "TICKET_CREATED": "工单已创建",
    "COMMENT_CREATED": "新增评论",
    "ASSIGNMENT_CREATED": "工单已派发",
    "ASSIGNMENT_ACCEPTED": "处理人已接受工单",
    "ASSIGNMENT_REJECTED": "处理人已拒绝工单",
    "ASSIGNMENT_COMPLETED": "处理人已完成工单",
    "ASSIGNMENT_SUPERSEDED": "原派发已重新分配",
    "TICKET_COMPLETED": "工单已完成",
    "TICKET_CLOSED": "工单已关闭",
    "TICKET_REOPENED": "工单已重新打开",
}


def _timeline_public(session: Session, audit: AuditLog) -> TimelineEventPublic:
    if audit.id is None:
        raise RuntimeError("persisted timeline row has no identity")
    if audit.ticket_id is None:
        raise RuntimeError("timeline audit row has no ticket")
    summary = _TIMELINE_SUMMARIES.get(audit.action)
    if summary is None:
        raise RuntimeError("timeline audit action is outside the public whitelist")
    return TimelineEventPublic(
        id=audit.id,
        event_type=cast(TimelineEventType, audit.action),
        actor=_actor_summary(session, audit.actor_user_id),
        ticket_id=audit.ticket_id,
        summary=summary,
        occurred_at=audit.created_at,
        event_metadata=_timeline_metadata(session, audit),
    )


def read_ticket_timeline(
    *,
    session: Session,
    actor: ActorContext,
    ticket_id: uuid.UUID,
    event_type: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    cursor: str | None,
    limit: int,
    sort: str,
) -> TimelineEventPage:
    """业务时间线继承 Ticket 可见性，只读取白名单事件并按时间正序分页。"""

    _ensure_ticket_visible(session=session, actor=actor, ticket_id=ticket_id)
    _parse_sort(sort=sort, allowed={"created_at:asc": "asc"})
    if event_type is not None and event_type not in TIMELINE_EVENT_TYPES:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The timeline event_type filter is invalid.",
        )
    created_from = _ensure_utc(created_from, field_name="created_from")
    created_to = _ensure_utc(created_to, field_name="created_to")
    filters = {
        "ticket_id": str(ticket_id),
        "event_type": event_type,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
    }
    statement = select(AuditLog).where(
        col(AuditLog.ticket_id) == ticket_id,
        col(AuditLog.action).in_(TIMELINE_EVENT_TYPES),
    )
    if event_type is not None:
        statement = statement.where(col(AuditLog.action) == event_type)
    if created_from is not None:
        statement = statement.where(col(AuditLog.created_at) >= created_from)
    if created_to is not None:
        statement = statement.where(col(AuditLog.created_at) < created_to)
    if cursor is not None:
        cursor_value, raw_cursor_id = _decode_cursor(
            cursor=cursor,
            resource="ticket_timeline",
            sort_name=sort,
            filters=filters,
        )
        try:
            cursor_id = int(raw_cursor_id)
        except ValueError as exc:
            raise _invalid_cursor() from exc
        statement = statement.where(
            or_(
                col(AuditLog.created_at) > cursor_value,
                and_(
                    col(AuditLog.created_at) == cursor_value,
                    col(AuditLog.id) > cursor_id,
                ),
            )
        )
    rows = list(
        session.exec(
            statement.order_by(
                col(AuditLog.created_at).asc(),
                col(AuditLog.id).asc(),
            ).limit(limit + 1)
        ).all()
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _cursor_payload(
            resource="ticket_timeline",
            sort_name=sort,
            filters=filters,
            value=last.created_at,
            row_id=last.id,
        )
    return TimelineEventPage(
        items=[_timeline_public(session, audit) for audit in page],
        next_cursor=next_cursor,
    )


def read_audit_log_page(
    *,
    session: Session,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    entity_key: str | None,
    ticket_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str | None,
    outcome: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    cursor: str | None,
    limit: int,
    sort: str,
) -> AuditLogPage:
    """Admin 原始审计查询支持契约字段和 JSONB 复合键定位。"""

    direction = _parse_sort(
        sort=sort,
        allowed={"created_at:desc": "desc", "created_at:asc": "asc"},
    )
    if entity_type is not None and entity_type not in AUDIT_ENTITY_TYPES:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The audit entity_type filter is invalid.",
        )
    if action is not None and action not in AUDIT_ACTIONS:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The audit action filter is invalid.",
        )
    if outcome is not None and outcome not in AUDIT_OUTCOMES:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The audit outcome filter is invalid.",
        )
    parsed_entity_key = _parse_entity_key(entity_key)
    created_from = _ensure_utc(created_from, field_name="created_from")
    created_to = _ensure_utc(created_to, field_name="created_to")
    filters = {
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "entity_key": parsed_entity_key,
        "ticket_id": str(ticket_id) if ticket_id else None,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "action": action,
        "outcome": outcome,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
    }
    statement = select(AuditLog)
    if entity_type is not None:
        statement = statement.where(col(AuditLog.entity_type) == entity_type)
    if entity_id is not None:
        statement = statement.where(col(AuditLog.entity_id) == entity_id)
    if parsed_entity_key is not None:
        statement = statement.where(
            col(AuditLog.entity_key).contains(parsed_entity_key)
        )
    if ticket_id is not None:
        statement = statement.where(col(AuditLog.ticket_id) == ticket_id)
    if actor_user_id is not None:
        statement = statement.where(col(AuditLog.actor_user_id) == actor_user_id)
    if action is not None:
        statement = statement.where(col(AuditLog.action) == action)
    if outcome is not None:
        statement = statement.where(col(AuditLog.outcome) == outcome)
    if created_from is not None:
        statement = statement.where(col(AuditLog.created_at) >= created_from)
    if created_to is not None:
        statement = statement.where(col(AuditLog.created_at) < created_to)
    if cursor is not None:
        cursor_value, raw_cursor_id = _decode_cursor(
            cursor=cursor,
            resource="audit_log",
            sort_name=sort,
            filters=filters,
        )
        try:
            cursor_id = int(raw_cursor_id)
        except ValueError as exc:
            raise _invalid_cursor() from exc
        cursor_condition = (
            or_(
                col(AuditLog.created_at) < cursor_value,
                and_(
                    col(AuditLog.created_at) == cursor_value,
                    col(AuditLog.id) < cursor_id,
                ),
            )
            if direction == "desc"
            else or_(
                col(AuditLog.created_at) > cursor_value,
                and_(
                    col(AuditLog.created_at) == cursor_value,
                    col(AuditLog.id) > cursor_id,
                ),
            )
        )
        statement = statement.where(cursor_condition)
    primary = col(AuditLog.created_at)
    identity = col(AuditLog.id)
    statement = statement.order_by(
        primary.desc() if direction == "desc" else primary.asc(),
        identity.desc() if direction == "desc" else identity.asc(),
    ).limit(limit + 1)
    rows = list(session.exec(statement).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _cursor_payload(
            resource="audit_log",
            sort_name=sort,
            filters=filters,
            value=last.created_at,
            row_id=last.id,
        )
    return AuditLogPage(
        items=[_audit_public(session, audit) for audit in page],
        next_cursor=next_cursor,
    )


def _notification_public(notification: Notification) -> NotificationPublic:
    payload = notification.payload if isinstance(notification.payload, dict) else {}
    title = payload.get("title")
    message = payload.get("message")
    if not isinstance(title, str) or not isinstance(message, str):
        raise RuntimeError("notification payload is missing public text")
    if notification.notification_type not in NOTIFICATION_TYPES:
        raise RuntimeError("notification type is outside the public whitelist")
    return NotificationPublic(
        id=notification.id,
        notification_type=notification.notification_type,
        ticket_id=notification.ticket_id,
        assignment_id=notification.assignment_id,
        title=title,
        message=message,
        created_at=notification.created_at,
    )


def read_notification_page(
    *,
    session: Session,
    actor: ActorContext,
    notification_type: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    cursor: str | None,
    limit: int,
    sort: str,
) -> NotificationPage:
    """通知列表从 SQL 边界强制接收人等于当前 Actor，客服端不能跨用户枚举。"""

    direction = _parse_sort(
        sort=sort,
        allowed={"created_at:desc": "desc", "created_at:asc": "asc"},
    )
    if (
        notification_type is not None
        and notification_type not in NOTIFICATION_TYPES
    ):
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The notification_type filter is invalid.",
        )
    created_from = _ensure_utc(created_from, field_name="created_from")
    created_to = _ensure_utc(created_to, field_name="created_to")
    filters = {
        "recipient_id": str(actor.user_id),
        "notification_type": notification_type,
        "created_from": created_from.isoformat() if created_from else None,
        "created_to": created_to.isoformat() if created_to else None,
    }
    statement = select(Notification).where(
        col(Notification.recipient_id) == actor.user_id
    )
    if notification_type is not None:
        statement = statement.where(
            col(Notification.notification_type) == notification_type
        )
    if created_from is not None:
        statement = statement.where(col(Notification.created_at) >= created_from)
    if created_to is not None:
        statement = statement.where(col(Notification.created_at) < created_to)
    if cursor is not None:
        cursor_value, raw_cursor_id = _decode_cursor(
            cursor=cursor,
            resource="notification",
            sort_name=sort,
            filters=filters,
        )
        cursor_id = _uuid_or_none(raw_cursor_id)
        if cursor_id is None:
            raise _invalid_cursor()
        cursor_condition = (
            or_(
                col(Notification.created_at) < cursor_value,
                and_(
                    col(Notification.created_at) == cursor_value,
                    col(Notification.id) < cursor_id,
                ),
            )
            if direction == "desc"
            else or_(
                col(Notification.created_at) > cursor_value,
                and_(
                    col(Notification.created_at) == cursor_value,
                    col(Notification.id) > cursor_id,
                ),
            )
        )
        statement = statement.where(cursor_condition)
    primary = col(Notification.created_at)
    identity = col(Notification.id)
    statement = statement.order_by(
        primary.desc() if direction == "desc" else primary.asc(),
        identity.desc() if direction == "desc" else identity.asc(),
    ).limit(limit + 1)
    rows = list(session.exec(statement).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _cursor_payload(
            resource="notification",
            sort_name=sort,
            filters=filters,
            value=last.created_at,
            row_id=last.id,
        )
    return NotificationPage(
        items=[_notification_public(notification) for notification in page],
        next_cursor=next_cursor,
    )


def read_notification(
    *,
    session: Session,
    actor: ActorContext,
    notification_id: uuid.UUID,
) -> NotificationPublic:
    notification = session.exec(
        select(Notification).where(
            col(Notification.id) == notification_id,
            col(Notification.recipient_id) == actor.user_id,
        )
    ).first()
    if notification is None:
        raise APIError(
            status_code=404,
            code="NOTIFICATION_NOT_FOUND",
            message="The notification does not exist.",
        )
    return _notification_public(notification)
