import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_
from sqlmodel import col, select

from app.api.deps import CurrentActor, SessionDep
from app.core.errors import APIError
from app.models import Team, TeamPage, TeamPublic

router = APIRouter(prefix="/teams", tags=["teams"])


def _encode_cursor(team: Team) -> str:
    """游标包含最终排序键，避免新增 Team 导致 offset 分页重复或漏项。"""

    payload = json.dumps(
        {"created_at": team.created_at.isoformat(), "id": str(team.id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The cursor is invalid.",
        ) from exc


@router.get("", response_model=TeamPage)
def read_teams(
    session: SessionDep,
    current_actor: CurrentActor,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    include_inactive: bool = False,
) -> TeamPage:
    """查询可建单 Team；只有 ADMIN 可以主动包含停用项。"""

    if include_inactive and "ADMIN" not in current_actor.roles:
        raise APIError(
            status_code=403,
            code="ROLE_REQUIRED",
            message="The ADMIN role is required to include inactive teams.",
        )

    statement = select(Team)
    if not include_inactive:
        statement = statement.where(Team.is_active)
    if cursor:
        created_at, team_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                col(Team.created_at) > created_at,
                and_(
                    col(Team.created_at) == created_at,
                    col(Team.id) > team_id,
                ),
            )
        )
    statement = statement.order_by(
        col(Team.created_at),
        col(Team.id),
    ).limit(limit + 1)
    teams = list(session.exec(statement).all())
    has_more = len(teams) > limit
    page = teams[:limit]
    next_cursor = _encode_cursor(page[-1]) if has_more and page else None
    return TeamPage(
        items=[TeamPublic.model_validate(team) for team in page],
        next_cursor=next_cursor,
    )


@router.get("/{team_id}", response_model=TeamPublic)
def read_team(
    team_id: uuid.UUID,
    session: SessionDep,
    current_actor: CurrentActor,
) -> TeamPublic:
    """返回 Team 详情；非 ADMIN 不得发现已停用的 Team。"""

    team = session.get(Team, team_id)
    if team is None or (
        not team.is_active and "ADMIN" not in current_actor.roles
    ):
        raise APIError(
            status_code=404,
            code="TEAM_NOT_FOUND",
            message="The team does not exist.",
        )
    return TeamPublic.model_validate(team)
