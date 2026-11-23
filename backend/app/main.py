import uuid
from pathlib import Path
from time import perf_counter

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import OperationalError
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.core.errors import (
    APIError,
    api_error_handler,
    database_error_handler,
    request_validation_error_handler,
    unhandled_exception_handler,
)
from app.core.logging import configure_logging, request_logger

FRONTEND_DIR = Path(__file__).parent / "frontend"
configure_logging()


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.FASTAPI_ENV != "development":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为响应、错误和服务日志提供稳定请求标识。"""

    started_at = perf_counter()
    status_code = 500
    exception_type: str | None = None
    incoming_request_id = request.headers.get("X-Request-ID")
    try:
        request_id = (
            str(uuid.UUID(incoming_request_id))
            if incoming_request_id
            else str(uuid.uuid4())
        )
    except ValueError:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        exception_type = type(exc).__name__
        raise
    finally:
        request_logger.info(
            "request_completed",
            extra={
                "event": "request_completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": max(0, int((perf_counter() - started_at) * 1000)),
                **(
                    {"exception_type": exception_type}
                    if exception_type
                    else {}
                ),
            },
        )


app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(RequestValidationError, request_validation_error_handler)
app.add_exception_handler(OperationalError, database_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_HOST],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.frontend("/", directory=FRONTEND_DIR)
