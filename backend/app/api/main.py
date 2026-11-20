from fastapi import APIRouter

from app.api.openapi import (
    AUTH_ERROR_RESPONSES,
    READ_ERROR_RESPONSES,
    RESOURCE_ERROR_RESPONSES,
)
from app.api.routes import (
    assignments,
    audit,
    comments,
    health,
    login,
    notifications,
    teams,
    tickets,
    users,
)

api_router = APIRouter()
api_router.include_router(login.router, responses=AUTH_ERROR_RESPONSES)
api_router.include_router(users.router, responses=RESOURCE_ERROR_RESPONSES)
api_router.include_router(teams.router, responses=RESOURCE_ERROR_RESPONSES)
api_router.include_router(tickets.router, responses=RESOURCE_ERROR_RESPONSES)
api_router.include_router(comments.router, responses=RESOURCE_ERROR_RESPONSES)
api_router.include_router(
    assignments.router,
    responses=RESOURCE_ERROR_RESPONSES,
)
api_router.include_router(audit.router, responses=AUTH_ERROR_RESPONSES)
api_router.include_router(
    notifications.router,
    responses=READ_ERROR_RESPONSES,
)
api_router.include_router(health.router)
