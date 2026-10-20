import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.errors import register_error_handlers
from app.api.openapi import SWAGGER_UI_PARAMETERS, TAGS
from app.api.router import api_router
from app.auth.authenticator import Authenticator
from app.auth.keys import KeyHasher
from app.auth.rate_limit import RateLimiter, RedisRateLimiter, UnlimitedRateLimiter
from app.core.logging import configure_logging
from app.core.settings import Settings, get_settings
from app.infra.database import Database
from app.ml.provider import LocalModels
from app.storage.crypto import cipher_from_settings
from app.storage.resolver import StorageResolver


def rate_limiter_for(settings: Settings, redis: Redis) -> RateLimiter:
    if settings.rate_limit_enabled:
        return RedisRateLimiter(redis)
    return UnlimitedRateLimiter()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database.from_settings(settings)
    redis = Redis.from_url(settings.redis_url)
    models = LocalModels(settings)
    if settings.preload_models:
        await asyncio.to_thread(models.warm_up)

    hasher = KeyHasher(settings.api_key_pepper)
    cipher = cipher_from_settings(settings)
    app.state.database = database
    app.state.models = models
    app.state.cipher = cipher
    app.state.storage = StorageResolver(settings, cipher)
    app.state.hasher = hasher
    app.state.authenticator = Authenticator(
        hasher,
        cache_seconds=settings.api_key_cache_seconds,
        touch_seconds=settings.api_key_touch_seconds,
    )
    app.state.rate_limiter = rate_limiter_for(settings, redis)
    yield
    await redis.aclose()
    await database.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        openapi_tags=TAGS,
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
