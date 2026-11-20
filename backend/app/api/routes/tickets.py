import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    ActorContext,
    CurrentActor,
    IdempotencyKey,
    SessionDep,
    require_roles,
)
from app.models import (
    CloseTicketRequest,
    ReopenTicketRequest,
    TicketCreateRequest,
    TicketDetailPublic,
    TicketMutationResponse,
    TicketPage,
    TicketUpdateRequest,
    TimelineEventPage,
)
from app.services import tickets as ticket_service
from app.services.activity import read_ticket_timeline
from app.services.assignments import (
    close_ticket as close_ticket_service,
)
from app.services.assignments import reopen_ticket as reopen_ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])

TicketCreator = Annotated[
    ActorContext,
    Depends(require_roles("SUBMITTER", "ADMIN")),
]


@router.get("", response_model=TicketPage)
def read_tickets(
    session: SessionDep,
    current_actor: CurrentActor,
    team_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    submitter_id: uuid.UUID | None = None,
    assigned_to_me: bool = False,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = "updated_at:desc",
) -> TicketPage:
    """按认证 Actor 的 SQL 可见范围查询 Ticket。"""

    return ticket_service.read_ticket_page(
        session=session,
        actor=current_actor,
        team_id=team_id,
        status=status_filter,
        submitter_id=submitter_id,
        assigned_to_me=assigned_to_me,
        created_from=created_from,
        created_to=created_to,
        cursor=cursor,
        limit=limit,
        sort=sort,
    )


@router.post("", response_model=TicketDetailPublic, status_code=status.HTTP_201_CREATED)
def create_ticket(
    session: SessionDep,
    current_actor: TicketCreator,
    idempotency_key: IdempotencyKey,
    ticket_in: TicketCreateRequest,
) -> TicketDetailPublic:
    """创建人由认证上下文决定，客户端不能提交状态或版本。"""

    return ticket_service.create_ticket(
        session=session,
        actor=current_actor,
        idempotency_key=idempotency_key,
        ticket_in=ticket_in,
    )


@router.get("/{ticket_id}", response_model=TicketDetailPublic)
def read_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
) -> TicketDetailPublic:
    """不存在与不可见统一返回 404，避免泄露资源存在性。"""

    return ticket_service.read_ticket_detail(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
    )


@router.get("/{ticket_id}/timeline", response_model=TimelineEventPage)
def read_timeline(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    event_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = "created_at:asc",
) -> TimelineEventPage:
    """时间线与 Ticket 详情复用同一可见性，且只输出受控业务摘要。"""

    return read_ticket_timeline(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        event_type=event_type,
        created_from=created_from,
        created_to=created_to,
        cursor=cursor,
        limit=limit,
        sort=sort,
    )


@router.patch("/{ticket_id}", response_model=TicketDetailPublic)
def update_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
    ticket_in: TicketUpdateRequest,
) -> TicketDetailPublic:
    """正文编辑只改变 ticket 自身字段，不触碰派发历史。"""

    return ticket_service.update_ticket(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        idempotency_key=idempotency_key,
        ticket_in=ticket_in,
    )


@router.post(
    "/{ticket_id}/actions/close",
    response_model=TicketMutationResponse,
)
def close_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
    close_in: CloseTicketRequest,
) -> TicketMutationResponse:
    """提交人或管理角色确认结果并关闭待确认工单。"""

    return close_ticket_service(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        idempotency_key=idempotency_key,
        close_in=close_in,
    )


@router.post(
    "/{ticket_id}/actions/reopen",
    response_model=TicketMutationResponse,
)
def reopen_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
    reopen_in: ReopenTicketRequest,
) -> TicketMutationResponse:
    """提交人或管理角色填写原因后重开已关闭工单。"""

    return reopen_ticket_service(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        idempotency_key=idempotency_key,
        reopen_in=reopen_in,
    )
