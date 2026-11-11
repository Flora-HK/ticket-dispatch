import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentActor, IdempotencyKey, SessionDep
from app.models import CommentCreateRequest, CommentPage, CommentPublic
from app.services import tickets as ticket_service

router = APIRouter(tags=["comments"])


@router.get("/tickets/{ticket_id}/comments", response_model=CommentPage)
def read_comments(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> CommentPage:
    """拥有 Ticket 查看权限的用户可以读取公开评论时间线。"""

    return ticket_service.read_comments(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/tickets/{ticket_id}/comments",
    response_model=CommentPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    ticket_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
    comment_in: CommentCreateRequest,
) -> CommentPublic:
    """评论写入由服务层锁 Ticket 后重新校验状态和版本。"""

    return ticket_service.create_comment(
        session=session,
        actor=current_actor,
        ticket_id=ticket_id,
        idempotency_key=idempotency_key,
        comment_in=comment_in,
    )
