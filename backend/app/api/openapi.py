from typing import Any

from app.models import ErrorResponse


def _error_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "model": ErrorResponse,
    }


# 所有公开错误都使用同一个 ErrorResponse，避免生成客户端读到模板默认的
# HTTPValidationError 形状而需要手工补类型。
AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _error_response("Authentication required or token invalid."),
    403: _error_response("The authenticated user cannot perform this operation."),
    422: _error_response("Request validation failed."),
}

RESOURCE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **AUTH_ERROR_RESPONSES,
    404: _error_response("The resource does not exist or is not visible."),
    409: _error_response("The resource changed or the operation conflicts."),
}

READ_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **AUTH_ERROR_RESPONSES,
    404: _error_response("The resource does not exist or is not visible."),
}
