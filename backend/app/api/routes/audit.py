import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ActorContext, SessionDep, require_roles
from app.models import AuditLogPage
from app.services.activity import read_audit_log_page

router = APIRouter(prefix="/admin/audit-logs", tags=["audit"])

AuditAdmin = Annotated[
    ActorContext,
    Depends(require_roles("ADMIN")),
]


@router.get("", response_model=AuditLogPage)
def read_audit_logs(
    session: SessionDep,
    _current_actor: AuditAdmin,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    entity_key: str | None = None,
    ticket_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    action: str | None = None,
    outcome: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = "created_at:desc",
) -> AuditLogPage:
    """原始审计只读且仅限 Admin；复合实体用 JSON entity_key 对象定位。"""

    return read_audit_log_page(
        session=session,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_key=entity_key,
        ticket_id=ticket_id,
        actor_user_id=actor_user_id,
        action=action,
        outcome=outcome,
        created_from=created_from,
        created_to=created_to,
        cursor=cursor,
        limit=limit,
        sort=sort,
    )
