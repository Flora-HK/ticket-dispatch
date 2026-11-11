import uuid
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """输出契约规定的 error 包装，并复用中间件生成的 request_id。"""

    if not isinstance(exc, APIError):
        raise exc
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
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


async def request_validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """把 Pydantic 校验错误转换为不包含原始输入的稳定 ErrorResponse。"""

    if not isinstance(exc, RequestValidationError):
        raise exc
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    fields = [
        {
            "loc": list(error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    response = JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "The request validation failed.",
                "request_id": request_id,
                "details": {"fields": fields},
            }
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response
