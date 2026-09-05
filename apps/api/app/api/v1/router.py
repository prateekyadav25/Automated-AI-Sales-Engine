from fastapi import APIRouter

from app.api.v1 import (
    acquisition,
    admin,
    ai,
    auth,
    autonomy,
    command_center,
    crm,
    discovery,
    imports,
    lifecycle,
    market,
    search,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(command_center.router)
api_router.include_router(crm.router)
api_router.include_router(ai.router)
api_router.include_router(search.router)
api_router.include_router(imports.router)
api_router.include_router(market.router)
api_router.include_router(acquisition.router)
api_router.include_router(lifecycle.router)
api_router.include_router(discovery.router)
api_router.include_router(autonomy.router)
