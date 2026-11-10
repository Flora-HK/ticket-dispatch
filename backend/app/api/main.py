from fastapi import APIRouter

from app.api.routes import items, login, teams, users, utils

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(teams.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
