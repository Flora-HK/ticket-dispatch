import uuid
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
    AcceptAssignmentRequest,
    ActiveAssignmentResponse,
    AssignmentPage,
    CompleteAssignmentRequest,
    DispatchCandidateListResponse,
    DispatchRequest,
    DispatchResponse,
    RejectAssignmentRequest,
    TicketMutationResponse,
)
from app.services.assignments import (
    accept_assignment,
    complete_assignment,
    read_active_assignment,
    read_assignment_page,
    read_dispatch_candidates,
    reject_assignment,
)
from app.services.assignments import dispatch_ticket as dispatch_ticket_service

router = APIRouter(tags=["assignments"])

DispatchManager = Annotated[
    ActorContext,
    Depends(require_roles("DISPATCHER", "ADMIN")),
]


@router.get(
    "/tickets/{ticket_id}/assignments",
    response_model=AssignmentPage,
)
def get_assignment_history(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    status_filter: str | None = Query(default=None, alias="status"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> AssignmentPage:
    """拥有 Ticket 查看权限的用户可以读取完整派发历史。"""

    return read_assignment_page(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        status_filter=status_filter,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/tickets/{ticket_id}/assignment",
    response_model=ActiveAssignmentResponse,
)
def get_active_assignment(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
) -> ActiveAssignmentResponse:
    """无活动派发时返回 200 和 null，而不是把“无处理人”当成错误。"""

    return read_active_assignment(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
    )


@router.get(
    "/tickets/{ticket_id}/dispatch-candidates",
    response_model=DispatchCandidateListResponse,
)
def get_dispatch_candidates(
    ticket_id: uuid.UUID,
    session: SessionDep,
    _current_actor: DispatchManager,
) -> DispatchCandidateListResponse:
    """Dispatcher/Admin 查看候选；不可派发状态返回空名单而非状态错误。"""

    return read_dispatch_candidates(session=session, ticket_id=ticket_id)


@router.post(
    "/tickets/{ticket_id}/dispatch",
    response_model=DispatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def dispatch_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: DispatchManager,
    idempotency_key: IdempotencyKey,
    dispatch_in: DispatchRequest,
) -> DispatchResponse:
    """人工或自动派发在 Team 与 Ticket 锁内重算候选并原子写入。"""

    return dispatch_ticket_service(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        idempotency_key=idempotency_key,
        dispatch_in=dispatch_in,
    )


@router.post(
    "/assignments/{assignment_id}/accept",
    response_model=TicketMutationResponse,
)
def accept_current_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
    accept_in: AcceptAssignmentRequest,
) -> TicketMutationResponse:
    """当前 Handler 接受派发，状态和版本必须与客户端看到的一致。"""

    return accept_assignment(
        session=session,
        actor=current_actor,
        assignment_id=assignment_id,
        idempotency_key=idempotency_key,
        accept_in=accept_in,
    )


@router.post(
    "/assignments/{assignment_id}/complete",
    response_model=TicketMutationResponse,
)
def complete_current_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
    complete_in: CompleteAssignmentRequest,
) -> TicketMutationResponse:
    """当前 Handler 提交完成说明，Ticket 进入待提交人确认。"""

    return complete_assignment(
        session=session,
        actor=current_actor,
        assignment_id=assignment_id,
        idempotency_key=idempotency_key,
        complete_in=complete_in,
    )


@router.post(
    "/assignments/{assignment_id}/reject",
    response_model=TicketMutationResponse,
)
def reject_current_assignment(
    assignment_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
    reject_in: RejectAssignmentRequest,
) -> TicketMutationResponse:
    """当前 Handler 拒绝派发，必须提供原因和双版本。"""

    return reject_assignment(
        session=session,
        actor=current_actor,
        assignment_id=assignment_id,
        idempotency_key=idempotency_key,
        reject_in=reject_in,
    )
