import uuid
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.core.logging import request_logger


class APIError(Exception):
    """携带稳定业务错误码的接口异常，由统一处理器转换为 ErrorResponse。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


_DATABASE_ERROR_CONTRACT = {
    "55P03": (
        "DATABASE_LOCK_TIMEOUT",
        "The database resource is temporarily locked. Please retry.",
    ),
    "57014": (
        "DATABASE_STATEMENT_TIMEOUT",
        "The database operation exceeded its allowed time.",
    ),
    "40001": (
        "DATABASE_RETRYABLE_TRANSACTION",
        "The database transaction must be retried.",
    ),
    "40P01": (
        "DATABASE_RETRYABLE_TRANSACTION",
        "The database transaction must be retried.",
    ),
}


def _sqlstate(exc: OperationalError) -> str | None:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate:
        return str(sqlstate)
    diagnostic = getattr(exc.orig, "diag", None)
    sqlstate = getattr(diagnostic, "sqlstate", None)
    return str(sqlstate) if sqlstate else None


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """输出契约规定的 error 包装，并复用中间件生成的 request_id。"""

    if not isinstance(exc, APIError):
        raise exc
    request_id = str(getattr(request.state, "request_id", uuid.uuid4()))
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
                "details": exc.details,
            }
        },
        headers=exc.headers,
    )
    response.headers["X-Request-ID"] = request_id
    return response


async def database_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Map transient database failures to a stable retryable response."""

    if not isinstance(exc, OperationalError):
        raise exc
    code, message = _DATABASE_ERROR_CONTRACT.get(
        _sqlstate(exc) or "",
        (
            "SERVICE_UNAVAILABLE",
            "The database is temporarily unavailable. Please retry.",
        ),
    )
    return await api_error_handler(
        request,
        APIError(
            status_code=503,
            code=code,
            message=message,
            details={"retryable": True},
            headers={"Retry-After": "1"},
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Return a safe contract response without exposing internal details."""

    request_id = str(getattr(request.state, "request_id", uuid.uuid4()))
    request_logger.error(
        "unhandled_exception",
        extra={
            "event": "unhandled_exception",
            "request_id": request_id,
            "exception_type": type(exc).__name__,
        },
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return await api_error_handler(
        request,
        APIError(
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred.",
        ),
    )


async def request_validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """把 Pydantic 校验错误转换为不包含原始输入的稳定 ErrorResponse。"""

    if not isinstance(exc, RequestValidationError):
        raise exc
    request_id = str(getattr(request.state, "request_id", uuid.uuid4()))
    fields = [
        {
            "loc": list(error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    field_names = {
        field["loc"][-1]
        for field in fields
        if field["loc"]
    }
    code = "VALIDATION_ERROR"
    if "reason" in field_names and (
        request.url.path.endswith("/reject")
        or request.url.path.endswith("/actions/reopen")
    ):
        code = "REASON_REQUIRED"
    elif "completion_note" in field_names:
        code = "COMPLETION_NOTE_REQUIRED"
    response = JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": code,
                "message": "The request validation failed.",
                "request_id": request_id,
                "details": {"fields": fields},
            }
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response
