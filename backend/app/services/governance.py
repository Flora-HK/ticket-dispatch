import base64
import binascii
import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import ActorContext
from app.core.errors import APIError
from app.core.security import get_password_hash
from app.models import (
    ROLE_CODES,
    AuditLog,
    RoleSetReplaceRequest,
    Team,
    TeamCreateRequest,
    TeamMembership,
    TeamMembershipMutationResponse,
    TeamMembershipPage,
    TeamMembershipPublic,
    TeamMembershipUpsertRequest,
    TeamPublic,
    TeamUpdateRequest,
    User,
    UserAdminUpdateRequest,
    UserCreateRequest,
    UserPage,
    UserPublic,
    UserRole,
    UserSelfUpdateRequest,
    UserSummary,
)
from app.services.idempotency import (
    begin_idempotent_command,
    finish_idempotent_command,
)


def _user_public(*, session: Session, user: User) -> UserPublic:
    stored_roles = set(
        session.exec(
            select(UserRole.role_code).where(col(UserRole.user_id) == user.id)
        ).all()
    )
    roles = [role for role in ROLE_CODES if role in stored_roles]
    return UserPublic.model_validate(user, update={"roles": roles})


def _admin_lock_id() -> int:
    digest = hashlib.sha256(b"governance:last-active-admin").digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _acquire_admin_lock(session: Session) -> None:
    session.exec(
        select(func.pg_advisory_xact_lock(_admin_lock_id()))
    ).one()


def _has_admin_role(session: Session, user_id: uuid.UUID) -> bool:
    return (
        session.exec(
            select(UserRole.id).where(
                col(UserRole.user_id) == user_id,
                col(UserRole.role_code) == "ADMIN",
            )
        ).first()
        is not None
    )


def _active_admin_count(session: Session) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(User)
            .join(UserRole, col(UserRole.user_id) == col(User.id))
            .where(
                col(User.is_active).is_(True),
                col(UserRole.role_code) == "ADMIN",
            )
        ).one()
    )


def _user_cursor(*, user: User, filters: dict[str, object]) -> str:
    payload = json.dumps(
        {
            "filters": filters,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "id": str(user.id),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_user_cursor(
    *, cursor: str, filters: dict[str, object]
) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if payload["filters"] != filters or payload["created_at"] is None:
            raise ValueError("cursor is bound to another query")
        date_value = datetime.fromisoformat(payload["created_at"])
        return date_value, uuid.UUID(payload["id"])
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


def list_users(
    *,
    session: Session,
    is_active: bool | None,
    role: str | None,
    cursor: str | None,
    limit: int,
) -> UserPage:
    """Admin 用户列表使用稳定键集分页，筛选条件绑定游标。"""

    if role is not None and role not in ROLE_CODES:
        raise APIError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The role filter is invalid.",
        )
    filters: dict[str, object] = {"is_active": is_active, "role": role}
    statement = select(User)
    if role is not None:
        statement = statement.join(
            UserRole, col(UserRole.user_id) == col(User.id)
        ).where(col(UserRole.role_code) == role)
    if is_active is not None:
        statement = statement.where(col(User.is_active) == is_active)
    if cursor is not None:
        created_at, user_id = _decode_user_cursor(cursor=cursor, filters=filters)
        statement = statement.where(
            (col(User.created_at) < created_at)
            | (
                (col(User.created_at) == created_at)
                & (col(User.id) < user_id)
            )
        )
    statement = statement.order_by(
        col(User.created_at).desc(),
        col(User.id).desc(),
    ).limit(limit + 1)
    rows = list(session.exec(statement).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    return UserPage(
        items=[_user_public(session=session, user=user) for user in page],
        next_cursor=(
            _user_cursor(user=page[-1], filters=filters)
            if has_more and page
            else None
        ),
    )


def read_user(*, session: Session, user_id: uuid.UUID) -> UserPublic:
    user = session.get(User, user_id)
    if user is None:
        raise APIError(
            status_code=404,
            code="USER_NOT_FOUND",
            message="The user does not exist.",
        )
    return _user_public(session=session, user=user)


def create_managed_user(
    *,
    session: Session,
    actor: ActorContext,
    idempotency_key: str,
    user_in: UserCreateRequest,
) -> UserPublic:
    payload = user_in.model_dump(mode="json")
    payload["password"] = user_in.password.get_secret_value()
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_USER",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return UserPublic.model_validate(reservation.replay.body)
        if session.exec(
            select(User.id).where(col(User.email) == str(user_in.email))
        ).first():
            raise APIError(
                status_code=409,
                code="EMAIL_ALREADY_EXISTS",
                message="The email address is already in use.",
            )
        user = User(
            email=user_in.email,
            full_name=user_in.full_name,
            hashed_password=get_password_hash(
                user_in.password.get_secret_value()
            ),
        )
        session.add(user)
        session.flush()
        for role in dict.fromkeys(user_in.roles):
            role_row = UserRole(user_id=user.id, role_code=role)
            session.add(role_row)
            session.flush()
            session.add(
                AuditLog(
                    actor_user_id=actor.user_id,
                    actor_type="USER",
                    action="USER_ROLES_CHANGED",
                    entity_type="USER_ROLE",
                    entity_id=role_row.id,
                    entity_key={
                        "user_id": str(user.id),
                        "role_code": role,
                    },
                    outcome="SUCCESS",
                    request_id=uuid.UUID(actor.request_id),
                    idempotency_key=idempotency_key,
                    detail={"role_codes": list(dict.fromkeys(user_in.roles))},
                )
            )
        result = _user_public(session=session, user=user)
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_USER",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=201,
            response_body=response_body,
            resource_type="USER",
            resource_id=user.id,
        )
        return result


def admin_update_user(
    *,
    session: Session,
    actor: ActorContext,
    user_id: uuid.UUID,
    idempotency_key: str,
    user_in: UserAdminUpdateRequest,
) -> UserPublic:
    """管理员账号修改先取全局治理锁，再锁 User 并保护最后一名 Admin。"""

    payload = user_in.model_dump(mode="json", exclude_unset=True)
    if user_in.password is not None:
        payload["password"] = user_in.password.get_secret_value()
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="ADMIN_UPDATE_USER",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return UserPublic.model_validate(reservation.replay.body)
        _acquire_admin_lock(session)
        user = session.exec(
            select(User)
            .where(col(User.id) == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if user is None:
            raise APIError(
                status_code=404,
                code="USER_NOT_FOUND",
                message="The user does not exist.",
            )
        if user.version != user_in.expected_user_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The user has changed. Reload and try again.",
                details={
                    "expected_user_version": user_in.expected_user_version,
                    "actual_user_version": user.version,
                },
            )
        if user_in.email is not None:
            existing = session.exec(
                select(User).where(col(User.email) == str(user_in.email))
            ).first()
            if existing is not None and existing.id != user.id:
                raise APIError(
                    status_code=409,
                    code="EMAIL_ALREADY_EXISTS",
                    message="The email address is already in use.",
                )
        next_active = (
            user_in.is_active
            if user_in.is_active is not None
            else user.is_active
        )
        if (
            user.is_active
            and not next_active
            and _has_admin_role(session, user.id)
            and _active_admin_count(session) <= 1
        ):
            raise APIError(
                status_code=409,
                code="LAST_ADMIN_REQUIRED",
                message="The last active administrator cannot be disabled.",
            )

        updates: dict[str, object] = {}
        for field in ("email", "full_name", "is_active"):
            value = getattr(user_in, field)
            if value is not None:
                updates[field] = value
        if user_in.password is not None:
            updates["hashed_password"] = get_password_hash(
                user_in.password.get_secret_value()
            )
        user.sqlmodel_update(updates)
        user.version += 1
        session.add(user)
        session.flush()
        result = _user_public(session=session, user=user)
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="USER_STATUS_CHANGED",
                entity_type="USER",
                entity_id=user.id,
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={"changed_fields": sorted(updates)},
            )
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="ADMIN_UPDATE_USER",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="USER",
            resource_id=user.id,
        )
        return result


def replace_user_roles(
    *,
    session: Session,
    actor: ActorContext,
    user_id: uuid.UUID,
    idempotency_key: str,
    roles_in: RoleSetReplaceRequest,
) -> UserPublic:
    """全量替换角色；全局 Admin 锁保证最后管理员检查不可被并发绕过。"""

    payload = roles_in.model_dump(mode="json")
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REPLACE_USER_ROLES",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return UserPublic.model_validate(reservation.replay.body)
        _acquire_admin_lock(session)
        user = session.exec(
            select(User)
            .where(col(User.id) == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if user is None:
            raise APIError(
                status_code=404,
                code="USER_NOT_FOUND",
                message="The user does not exist.",
            )
        if user.version != roles_in.expected_user_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The user has changed. Reload and try again.",
                details={
                    "expected_user_version": roles_in.expected_user_version,
                    "actual_user_version": user.version,
                },
            )

        desired_roles = list(dict.fromkeys(roles_in.roles))
        current_rows = list(
            session.exec(
                select(UserRole)
                .where(col(UserRole.user_id) == user.id)
                .with_for_update()
            ).all()
        )
        current_roles = {row.role_code for row in current_rows}
        desired = set(desired_roles)
        for row in current_rows:
            if row.role_code not in desired:
                session.add(
                    AuditLog(
                        actor_user_id=actor.user_id,
                        actor_type="USER",
                        action="USER_ROLES_CHANGED",
                        entity_type="USER_ROLE",
                        entity_id=row.id,
                        entity_key={
                            "user_id": str(user.id),
                            "role_code": row.role_code,
                        },
                        outcome="SUCCESS",
                        request_id=uuid.UUID(actor.request_id),
                        idempotency_key=idempotency_key,
                        detail={"role_codes": desired_roles},
                    )
                )
                session.delete(row)
        for role in desired_roles:
            if role in current_roles:
                continue
            role_row = UserRole(user_id=user.id, role_code=role)
            session.add(role_row)
            session.flush()
            session.add(
                AuditLog(
                    actor_user_id=actor.user_id,
                    actor_type="USER",
                    action="USER_ROLES_CHANGED",
                    entity_type="USER_ROLE",
                    entity_id=role_row.id,
                    entity_key={
                        "user_id": str(user.id),
                        "role_code": role,
                    },
                    outcome="SUCCESS",
                    request_id=uuid.UUID(actor.request_id),
                    idempotency_key=idempotency_key,
                    detail={"role_codes": desired_roles},
                )
            )
        user.version += 1
        session.add(user)
        session.flush()
        if _active_admin_count(session) == 0:
            raise APIError(
                status_code=409,
                code="LAST_ADMIN_REQUIRED",
                message="At least one active administrator is required.",
            )
        result = _user_public(session=session, user=user)
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REPLACE_USER_ROLES",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="USER",
            resource_id=user.id,
        )
        return result


def _team_public(team: Team) -> TeamPublic:
    return TeamPublic.model_validate(team)


def create_team_managed(
    *,
    session: Session,
    actor: ActorContext,
    idempotency_key: str,
    team_in: TeamCreateRequest,
) -> TeamPublic:
    payload = team_in.model_dump(mode="json")
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_TEAM",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TeamPublic.model_validate(reservation.replay.body)
        existing = session.exec(
            select(Team.id).where(
                col(Team.name) == team_in.name,
                col(Team.is_active).is_(True),
            )
        ).first()
        if existing is not None:
            raise APIError(
                status_code=409,
                code="TEAM_NAME_CONFLICT",
                message="An active team with this name already exists.",
            )
        team = Team(name=team_in.name)
        session.add(team)
        session.flush()
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="TEAM_MEMBER_CHANGED",
                entity_type="TEAM",
                entity_id=team.id,
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={"changed_fields": ["name", "is_active"]},
            )
        )
        result = _team_public(team)
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="CREATE_TEAM",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=201,
            response_body=result.model_dump(mode="json"),
            resource_type="TEAM",
            resource_id=team.id,
        )
        return result


def update_team_managed(
    *,
    session: Session,
    actor: ActorContext,
    team_id: uuid.UUID,
    idempotency_key: str,
    team_in: TeamUpdateRequest,
) -> TeamPublic:
    payload = {
        "team_id": str(team_id),
        **team_in.model_dump(mode="json", exclude_unset=True),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPDATE_TEAM",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TeamPublic.model_validate(reservation.replay.body)
        team = session.exec(
            select(Team)
            .where(col(Team.id) == team_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if team is None:
            raise APIError(
                status_code=404,
                code="TEAM_NOT_FOUND",
                message="The team does not exist.",
            )
        if team.version != team_in.expected_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The team has changed. Reload and try again.",
                details={
                    "expected_version": team_in.expected_version,
                    "actual_version": team.version,
                },
            )
        if team_in.name is not None:
            existing = session.exec(
                select(Team.id).where(
                    col(Team.name) == team_in.name,
                    col(Team.is_active).is_(True),
                    col(Team.id) != team.id,
                )
            ).first()
            if existing is not None:
                raise APIError(
                    status_code=409,
                    code="TEAM_NAME_CONFLICT",
                    message="An active team with this name already exists.",
                )
        updates = team_in.model_dump(
            exclude={"expected_version"},
            exclude_none=True,
        )
        team.sqlmodel_update(updates)
        team.version += 1
        session.add(team)
        session.flush()
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="TEAM_MEMBER_CHANGED",
                entity_type="TEAM",
                entity_id=team.id,
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={"changed_fields": sorted(updates)},
            )
        )
        result = _team_public(team)
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPDATE_TEAM",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=result.model_dump(mode="json"),
            resource_type="TEAM",
            resource_id=team.id,
        )
        return result


def _membership_public(
    *, session: Session, membership: TeamMembership
) -> TeamMembershipPublic:
    user = session.get(User, membership.user_id)
    if user is None:
        raise RuntimeError("membership user is missing")
    return TeamMembershipPublic(
        id=membership.id,
        user=UserSummary.model_validate(user),
        is_available=membership.is_available,
        last_assigned_at=membership.last_assigned_at,
        joined_at=membership.joined_at,
    )


def _membership_cursor(
    *, membership: TeamMembership, team_id: uuid.UUID, is_available: bool | None
) -> str:
    payload = json.dumps(
        {
            "team_id": str(team_id),
            "is_available": is_available,
            "joined_at": membership.joined_at.isoformat(),
            "id": str(membership.id),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_membership_cursor(
    *, cursor: str, team_id: uuid.UUID, is_available: bool | None
) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if (
            payload["team_id"] != str(team_id)
            or payload["is_available"] != is_available
        ):
            raise ValueError("cursor is bound to another query")
        return datetime.fromisoformat(payload["joined_at"]), uuid.UUID(
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


def list_team_members(
    *,
    session: Session,
    actor: ActorContext,
    team_id: uuid.UUID,
    is_available: bool | None,
    cursor: str | None,
    limit: int,
) -> TeamMembershipPage:
    team = session.get(Team, team_id)
    if team is None or (
        not team.is_active and "ADMIN" not in actor.roles
    ):
        raise APIError(
            status_code=404,
            code="TEAM_NOT_FOUND",
            message="The team does not exist.",
        )
    statement = select(TeamMembership).where(
        col(TeamMembership.team_id) == team.id
    )
    if is_available is not None:
        statement = statement.where(
            col(TeamMembership.is_available) == is_available
        )
    if cursor is not None:
        joined_at, membership_id = _decode_membership_cursor(
            cursor=cursor,
            team_id=team.id,
            is_available=is_available,
        )
        statement = statement.where(
            (col(TeamMembership.joined_at) > joined_at)
            | (
                (col(TeamMembership.joined_at) == joined_at)
                & (col(TeamMembership.id) > membership_id)
            )
        )
    statement = statement.order_by(
        col(TeamMembership.joined_at),
        col(TeamMembership.id),
    ).limit(limit + 1)
    rows = list(session.exec(statement).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    return TeamMembershipPage(
        team_id=team.id,
        team_version=team.version,
        items=[
            _membership_public(session=session, membership=row)
            for row in page
        ],
        next_cursor=(
            _membership_cursor(
                membership=page[-1],
                team_id=team.id,
                is_available=is_available,
            )
            if has_more and page
            else None
        ),
    )


def upsert_team_member(
    *,
    session: Session,
    actor: ActorContext,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    idempotency_key: str,
    membership_in: TeamMembershipUpsertRequest,
) -> TeamMembershipMutationResponse:
    payload = {
        "team_id": str(team_id),
        "user_id": str(user_id),
        **membership_in.model_dump(mode="json"),
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPSERT_TEAM_MEMBER",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TeamMembershipMutationResponse.model_validate(
                reservation.replay.body
            )
        team = session.exec(
            select(Team)
            .where(col(Team.id) == team_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if team is None:
            raise APIError(
                status_code=404,
                code="TEAM_NOT_FOUND",
                message="The team does not exist.",
            )
        if team.version != membership_in.expected_team_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The team has changed. Reload and try again.",
                details={
                    "expected_version": membership_in.expected_team_version,
                    "actual_version": team.version,
                },
            )
        user = session.get(User, user_id)
        if user is None:
            raise APIError(
                status_code=404,
                code="USER_NOT_FOUND",
                message="The user does not exist.",
            )
        membership = session.exec(
            select(TeamMembership)
            .where(
                col(TeamMembership.team_id) == team.id,
                col(TeamMembership.user_id) == user.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if membership is None:
            membership = TeamMembership(
                team_id=team.id,
                user_id=user.id,
                is_available=membership_in.is_available,
            )
        else:
            membership.is_available = membership_in.is_available
        session.add(membership)
        team.version += 1
        session.add(team)
        session.flush()
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="TEAM_MEMBER_CHANGED",
                entity_type="TEAM_MEMBERSHIP",
                entity_id=membership.id,
                entity_key={
                    "team_id": str(team.id),
                    "user_id": str(user.id),
                },
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={"changed_fields": ["is_available"]},
            )
        )
        result = TeamMembershipMutationResponse(
            membership=_membership_public(session=session, membership=membership),
            removed_user_id=None,
            team_version=team.version,
        )
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPSERT_TEAM_MEMBER",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=result.model_dump(mode="json"),
            resource_type="TEAM_MEMBERSHIP",
            resource_id=membership.id,
        )
        return result


def remove_team_member(
    *,
    session: Session,
    actor: ActorContext,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    expected_team_version: int,
    idempotency_key: str,
) -> TeamMembershipMutationResponse:
    payload = {
        "team_id": str(team_id),
        "user_id": str(user_id),
        "expected_team_version": expected_team_version,
    }
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REMOVE_TEAM_MEMBER",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return TeamMembershipMutationResponse.model_validate(
                reservation.replay.body
            )
        team = session.exec(
            select(Team)
            .where(col(Team.id) == team_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if team is None:
            raise APIError(
                status_code=404,
                code="TEAM_NOT_FOUND",
                message="The team does not exist.",
            )
        if team.version != expected_team_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The team has changed. Reload and try again.",
                details={
                    "expected_version": expected_team_version,
                    "actual_version": team.version,
                },
            )
        membership = session.exec(
            select(TeamMembership)
            .where(
                col(TeamMembership.team_id) == team.id,
                col(TeamMembership.user_id) == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if membership is None:
            raise APIError(
                status_code=404,
                code="USER_NOT_FOUND",
                message="The team membership does not exist.",
            )
        membership_id = membership.id
        session.delete(membership)
        team.version += 1
        session.add(team)
        session.flush()
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="TEAM_MEMBER_CHANGED",
                entity_type="TEAM_MEMBERSHIP",
                entity_id=membership_id,
                entity_key={
                    "team_id": str(team.id),
                    "user_id": str(user_id),
                },
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={"changed_fields": ["membership_removed"]},
            )
        )
        result = TeamMembershipMutationResponse(
            membership=None,
            removed_user_id=user_id,
            team_version=team.version,
        )
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="REMOVE_TEAM_MEMBER",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=result.model_dump(mode="json"),
            resource_type="TEAM_MEMBERSHIP",
            resource_id=membership_id,
        )
        return result


def update_current_user(
    *,
    session: Session,
    actor: ActorContext,
    idempotency_key: str,
    user_in: UserSelfUpdateRequest,
) -> UserPublic:
    """本人资料修改使用用户版本、行锁、幂等记录和追加审计。"""

    payload = user_in.model_dump(mode="json", exclude_unset=True)
    if session.in_transaction():
        session.rollback()
    with session.begin():
        reservation = begin_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPDATE_SELF",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if reservation.replay is not None:
            return UserPublic.model_validate(reservation.replay.body)

        user = session.exec(
            select(User)
            .where(col(User.id) == actor.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        if user.version != user_in.expected_user_version:
            raise APIError(
                status_code=409,
                code="STALE_VERSION",
                message="The user has changed. Reload and try again.",
                details={
                    "expected_user_version": user_in.expected_user_version,
                    "actual_user_version": user.version,
                },
            )
        if user_in.email is not None:
            existing = session.exec(
                select(User).where(col(User.email) == str(user_in.email))
            ).first()
            if existing is not None and existing.id != user.id:
                raise APIError(
                    status_code=409,
                    code="EMAIL_ALREADY_EXISTS",
                    message="The email address is already in use.",
                )

        updates = user_in.model_dump(
            mode="json",
            exclude={"expected_user_version"},
            exclude_none=True,
        )
        user.sqlmodel_update(updates)
        user.version += 1
        session.add(user)
        session.flush()
        result = _user_public(session=session, user=user)
        session.add(
            AuditLog(
                actor_user_id=actor.user_id,
                actor_type="USER",
                action="USER_STATUS_CHANGED",
                entity_type="USER",
                entity_id=user.id,
                before_state=None,
                after_state=None,
                outcome="SUCCESS",
                request_id=uuid.UUID(actor.request_id),
                idempotency_key=idempotency_key,
                detail={"changed_fields": sorted(updates)},
            )
        )
        response_body = result.model_dump(mode="json")
        finish_idempotent_command(
            session=session,
            actor_user_id=actor.user_id,
            command_scope="UPDATE_SELF",
            idempotency_key=idempotency_key,
            reservation=reservation,
            response_status=200,
            response_body=response_body,
            resource_type="USER",
            resource_id=user.id,
        )
        return result
