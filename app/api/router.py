from fastapi import APIRouter

from app.api.routes import (
    admin,
    api_keys,
    collections,
    documents,
    health,
    image_search,
    ingest,
    search,
    storage_connections,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(collections.router)
api_router.include_router(ingest.router)
api_router.include_router(documents.router)
api_router.include_router(search.router)
api_router.include_router(image_search.router)
api_router.include_router(storage_connections.router)
api_router.include_router(api_keys.router)
api_router.include_router(admin.router)
