import base64
import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_
from sqlmodel import col, select

from app.api.deps import (
    ActorContext,
    CurrentActor,
    IdempotencyKey,
    SessionDep,
    get_current_admin,
    require_roles,
)
from app.core.errors import APIError
from app.models import (
    Team,
    TeamCreateRequest,
    TeamMembershipMutationResponse,
    TeamMembershipPage,
    TeamMembershipUpsertRequest,
    TeamPage,
    TeamPublic,
    TeamUpdateRequest,
)
from app.services.governance import (
    create_team_managed,
    list_team_members,
    remove_team_member,
    update_team_managed,
    upsert_team_member,
)

router = APIRouter(prefix="/teams", tags=["teams"])

TeamMemberManager = Annotated[
    ActorContext,
    Depends(require_roles("DISPATCHER", "ADMIN")),
]


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


@router.post(
    "",
    dependencies=[Depends(get_current_admin)],
    response_model=TeamPublic,
    status_code=201,
)
def create_team(
    *,
    session: SessionDep,
    current_actor: CurrentActor,
    team_in: TeamCreateRequest,
    idempotency_key: IdempotencyKey,
) -> TeamPublic:
    return create_team_managed(
        session=session,
        actor=current_actor,
        idempotency_key=idempotency_key,
        team_in=team_in,
    )


@router.patch(
    "/{team_id}",
    dependencies=[Depends(get_current_admin)],
    response_model=TeamPublic,
)
def update_team(
    *,
    session: SessionDep,
    current_actor: CurrentActor,
    team_id: uuid.UUID,
    team_in: TeamUpdateRequest,
    idempotency_key: IdempotencyKey,
) -> TeamPublic:
    return update_team_managed(
        session=session,
        actor=current_actor,
        team_id=team_id,
        idempotency_key=idempotency_key,
        team_in=team_in,
    )


@router.get(
    "/{team_id}/members",
    response_model=TeamMembershipPage,
)
def read_team_members(
    team_id: uuid.UUID,
    session: SessionDep,
    current_actor: TeamMemberManager,
    is_available: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> TeamMembershipPage:
    return list_team_members(
        session=session,
        actor=current_actor,
        team_id=team_id,
        is_available=is_available,
        cursor=cursor,
        limit=limit,
    )


@router.put(
    "/{team_id}/members/{user_id}",
    dependencies=[Depends(get_current_admin)],
    response_model=TeamMembershipMutationResponse,
)
def upsert_member(
    *,
    session: SessionDep,
    current_actor: CurrentActor,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    membership_in: TeamMembershipUpsertRequest,
    idempotency_key: IdempotencyKey,
) -> TeamMembershipMutationResponse:
    return upsert_team_member(
        session=session,
        actor=current_actor,
        team_id=team_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
        membership_in=membership_in,
    )


@router.delete(
    "/{team_id}/members/{user_id}",
    dependencies=[Depends(get_current_admin)],
    response_model=TeamMembershipMutationResponse,
)
def delete_member(
    *,
    session: SessionDep,
    current_actor: CurrentActor,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    expected_team_version: int = Query(ge=1),
    idempotency_key: IdempotencyKey,
) -> TeamMembershipMutationResponse:
    return remove_team_member(
        session=session,
        actor=current_actor,
        team_id=team_id,
        user_id=user_id,
        expected_team_version=expected_team_version,
        idempotency_key=idempotency_key,
    )
