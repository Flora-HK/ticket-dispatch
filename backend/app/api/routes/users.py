import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, delete

from app import crud
from app.api.deps import (
    CurrentActor,
    IdempotencyKey,
    SessionDep,
    get_current_admin,
)
from app.core.errors import APIError
from app.core.security import get_password_hash, verify_password
from app.models import (
    Item,
    Message,
    RoleSetReplaceRequest,
    UpdatePassword,
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


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_actor: CurrentActor
) -> Any:
    """
    Update own password.
    """
    current_user = current_actor.user
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(session: SessionDep, current_actor: CurrentActor) -> Any:
    """
    Get current user.
    """
    return crud.to_user_public(session=session, user=current_actor.user)


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_actor: CurrentActor) -> Any:
    """
    Delete own user.
    """
    if current_actor.has_any_role(("ADMIN",)):
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    session.delete(current_actor.user)
    session.commit()
    return Message(message="User deleted successfully")


@router.post("/signup", include_in_schema=False)
def register_user() -> Any:
    """公开注册已关闭，账号统一由管理员创建。"""

    raise APIError(
        status_code=404,
        code="REGISTRATION_DISABLED",
        message="Public registration is disabled.",
    )


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


@router.delete("/{user_id}", dependencies=[Depends(get_current_admin)])
def delete_user(
    session: SessionDep, current_actor: CurrentActor, user_id: uuid.UUID
) -> Message:
    """
    Delete a user.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_actor.user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    statement = delete(Item).where(col(Item.owner_id) == user_id)
    session.exec(statement)
    session.delete(user)
    session.commit()
    return Message(message="User deleted successfully")
