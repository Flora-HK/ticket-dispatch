from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app import crud
from app.api.deps import SessionDep
from app.core import security
from app.core.config import settings
from app.core.errors import APIError
from app.models import TokenResponse

router = APIRouter(tags=["auth"])


@router.post("/login/access-token", response_model=TokenResponse)
def login_access_token(
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    """OAuth2 密码登录只签发短期访问令牌，权限仍从数据库实时加载。"""

    user = crud.authenticate(
        session=session,
        email=form_data.username,
        password=form_data.password,
    )
    if not user:
        raise APIError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="The email or password is incorrect.",
        )
    if not user.is_active:
        raise APIError(
            status_code=403,
            code="INACTIVE_USER",
            message="The user account is inactive.",
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return TokenResponse(
        access_token=security.create_access_token(
            user.id,
            expires_delta=access_token_expires,
        )
    )
