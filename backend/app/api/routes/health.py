from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.api.deps import SessionDep
from app.api.openapi import _error_response
from app.core.config import settings
from app.core.errors import APIError
from app.models import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


def check_database(session: Session) -> None:
    """ready 只做轻量连接探测，不暴露连接串或数据库内部状态。"""

    session.connection().execute(text("SELECT 1"))


@router.get("/live", response_model=HealthResponse)
def read_liveness() -> HealthResponse:
    """进程存活检查刻意不依赖数据库，便于区分应用与基础设施故障。"""

    return HealthResponse(status="ok", service=settings.PROJECT_NAME)


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: _error_response("Database is unavailable.")},
)
def read_readiness(session: SessionDep) -> HealthResponse:
    """数据库不可达时返回统一 503，而不是让底层驱动异常冒泡。"""

    try:
        check_database(session)
    except SQLAlchemyError as exc:
        raise APIError(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The service database is unavailable.",
        ) from exc
    return HealthResponse(status="ok", service=settings.PROJECT_NAME)
