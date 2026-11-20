import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import CurrentActor, SessionDep
from app.models import NotificationPage, NotificationPublic
from app.services.activity import read_notification, read_notification_page

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
def read_notifications(
    session: SessionDep,
    current_actor: CurrentActor,
    notification_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = "created_at:desc",
) -> NotificationPage:
    """只查询当前接收人的通知，MVP 不提供已读写入或跨用户查询。"""

    return read_notification_page(
        session=session,
        actor=current_actor,
        notification_type=notification_type,
        created_from=created_from,
        created_to=created_to,
        cursor=cursor,
        limit=limit,
        sort=sort,
    )


@router.get("/{notification_id}", response_model=NotificationPublic)
def read_notification_detail(
    notification_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
) -> NotificationPublic:
    """他人通知与不存在通知统一返回 404，避免泄露通知标识存在性。"""

    return read_notification(
        session=session,
        actor=current_actor,
        notification_id=notification_id,
    )
