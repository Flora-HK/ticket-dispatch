import uuid

from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import (
    CurrentActor,
    IdempotencyKey,
    SessionDep,
    get_current_admin,
)
from app.models import (
    RoleSetReplaceRequest,
    User,
    UserAdminUpdateRequest,
    UserCreateRequest,
    UserPage,
    UserPublic,
    UserSelfUpdateRequest,
)
from app.services.governance import (
    admin_update_user,
    create_managed_user,
    list_users,
    read_user,
    replace_user_roles,
    update_current_user,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    dependencies=[Depends(get_current_admin)],
    response_model=UserPage,
)
def read_users(
    session: SessionDep,
    cursor: str | None = None,
    limit: int = 100,
    is_active: bool | None = None,
    role: str | None = None,
) -> UserPage:
    return list_users(
        session=session,
        is_active=is_active,
        role=role,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "",
    dependencies=[Depends(get_current_admin)],
    response_model=UserPublic,
    status_code=201,
)
def create_user(
    *,
    session: SessionDep,
    current_actor: CurrentActor,
    user_in: UserCreateRequest,
    idempotency_key: IdempotencyKey,
) -> UserPublic:
    return create_managed_user(
        session=session,
        actor=current_actor,
        idempotency_key=idempotency_key,
        user_in=user_in,
    )


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *,
    session: SessionDep,
    user_in: UserSelfUpdateRequest,
    current_actor: CurrentActor,
    idempotency_key: IdempotencyKey,
) -> UserPublic:
    """本人资料修改走版本、幂等、行锁和审计事务。"""

    return update_current_user(
        session=session,
        actor=current_actor,
        idempotency_key=idempotency_key,
        user_in=user_in,
    )


@router.get("/me", response_model=UserPublic)
def read_user_me(session: SessionDep, current_actor: CurrentActor) -> UserPublic:
    """
    Get current user.
    """
    return crud.to_user_public(session=session, user=current_actor.user)


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID,
    session: SessionDep,
    _current_admin: User = Depends(get_current_admin),
) -> UserPublic:
    return read_user(session=session, user_id=user_id)


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_admin)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    current_actor: CurrentActor,
    user_in: UserAdminUpdateRequest,
    idempotency_key: IdempotencyKey,
) -> UserPublic:
    return admin_update_user(
        session=session,
        actor=current_actor,
        user_id=user_id,
        idempotency_key=idempotency_key,
        user_in=user_in,
    )


@router.put(
    "/{user_id}/roles",
    dependencies=[Depends(get_current_admin)],
    response_model=UserPublic,
)
def replace_roles(
    *,
    session: SessionDep,
    current_actor: CurrentActor,
    user_id: uuid.UUID,
    roles_in: RoleSetReplaceRequest,
    idempotency_key: IdempotencyKey,
) -> UserPublic:
    return replace_user_roles(
        session=session,
        actor=current_actor,
        user_id=user_id,
        idempotency_key=idempotency_key,
        roles_in=roles_in,
    )
