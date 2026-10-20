import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authenticator import Authenticator
from app.auth.keys import KeyHasher, grants
from app.auth.principal import Principal, TenantRef
from app.auth.rate_limit import RateBucket, RateLimiter, limit_for
from app.auth.service import ApiKeyService, TenantService
from app.core.errors import (
    ForbiddenError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.core.settings import Settings, get_settings
from app.domain.enums import ApiKeyScope
from app.domain.interfaces import ModelProvider
from app.infra.database import Database
from app.ingestion.service import IngestionService
from app.pipelines.registry import ExtractorRegistry, default_registry
from app.search.images import ImageSearchService
from app.search.service import SearchService
from app.storage.crypto import SecretCipher
from app.storage.resolver import StorageResolver

SettingsDep = Annotated[Settings, Depends(get_settings)]

api_key_bearer = HTTPBearer(
    scheme_name="ApiKey",
    description="Tenant API key, e.g. `rag_3fA9kQ2x_...`.",
    auto_error=False,
)
platform_bearer = HTTPBearer(
    scheme_name="PlatformAdmin",
    description="Platform admin key from `RAG_PLATFORM_ADMIN_KEY`.",
    auto_error=False,
)


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_models(request: Request) -> ModelProvider:
    models: ModelProvider = request.app.state.models
    return models


def get_storage(request: Request) -> StorageResolver:
    storage: StorageResolver = request.app.state.storage
    return storage


def get_cipher(request: Request) -> SecretCipher:
    cipher: SecretCipher = request.app.state.cipher
    return cipher


def get_authenticator(request: Request) -> Authenticator:
    authenticator: Authenticator = request.app.state.authenticator
    return authenticator


def get_hasher(request: Request) -> KeyHasher:
    hasher: KeyHasher = request.app.state.hasher
    return hasher


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


ModelsDep = Annotated[ModelProvider, Depends(get_models)]
StorageDep = Annotated[StorageResolver, Depends(get_storage)]
CipherDep = Annotated[SecretCipher, Depends(get_cipher)]
AuthenticatorDep = Annotated[Authenticator, Depends(get_authenticator)]
HasherDep = Annotated[KeyHasher, Depends(get_hasher)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
BearerCredentials = HTTPAuthorizationCredentials | None


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_principal(
    session: SessionDep,
    authenticator: AuthenticatorDep,
    credentials: Annotated[BearerCredentials, Security(api_key_bearer)],
) -> Principal:
    if credentials is None:
        raise UnauthorizedError("Send your API key as 'Authorization: Bearer <key>'")
    return await authenticator.authenticate(session, credentials.credentials)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def authorize(
    scope: ApiKeyScope,
    bucket: RateBucket,
) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: PrincipalDep,
        limiter: RateLimiterDep,
        settings: SettingsDep,
        response: Response,
    ) -> Principal:
        if not grants(principal.scopes, scope):
            raise ForbiddenError(f"This API key needs the '{scope}' scope")
        if not settings.rate_limit_enabled:
            return principal

        decision = await limiter.hit(
            f"{bucket}:{principal.key_id}",
            limit_for(bucket, principal.tenant.settings, settings),
            settings.rate_limit_window_seconds,
        )
        headers = decision.headers()
        if not decision.allowed:
            raise RateLimitedError(
                "Rate limit exceeded",
                headers | {"Retry-After": str(decision.reset_seconds)},
            )
        response.headers.update(headers)
        return principal

    return dependency


def scoped_tenant(
    scope: ApiKeyScope,
    bucket: RateBucket,
) -> Callable[..., Awaitable[TenantRef]]:
    authorized = authorize(scope, bucket)

    async def dependency(principal: Annotated[Principal, Depends(authorized)]) -> TenantRef:
        return principal.tenant

    return dependency


AdminPrincipal = Annotated[Principal, Depends(authorize(ApiKeyScope.ADMIN, RateBucket.API))]
SearchTenant = Annotated[TenantRef, Depends(scoped_tenant(ApiKeyScope.SEARCH, RateBucket.SEARCH))]
ReaderTenant = Annotated[TenantRef, Depends(scoped_tenant(ApiKeyScope.SEARCH, RateBucket.API))]
IngestTenant = Annotated[TenantRef, Depends(scoped_tenant(ApiKeyScope.INGEST, RateBucket.INGEST))]
EditorTenant = Annotated[TenantRef, Depends(scoped_tenant(ApiKeyScope.INGEST, RateBucket.API))]
AdminTenant = Annotated[TenantRef, Depends(scoped_tenant(ApiKeyScope.ADMIN, RateBucket.API))]


async def require_platform_admin(
    settings: SettingsDep,
    credentials: Annotated[BearerCredentials, Security(platform_bearer)],
) -> None:
    if not settings.platform_admin_key:
        raise ServiceUnavailableError("Platform admin API is disabled; set RAG_PLATFORM_ADMIN_KEY")
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(),
        settings.platform_admin_key.encode(),
    ):
        raise UnauthorizedError("Invalid platform admin key")


PlatformAdmin = Depends(require_platform_admin)


def get_extractors(models: ModelsDep, settings: SettingsDep) -> ExtractorRegistry:
    return default_registry(models, settings)


def get_ingestion_service(
    session: SessionDep,
    settings: SettingsDep,
    extractors: Annotated[ExtractorRegistry, Depends(get_extractors)],
    storage: StorageDep,
) -> IngestionService:
    return IngestionService(session, extractors, storage, settings)


def get_search_service(session: SessionDep, models: ModelsDep) -> SearchService:
    return SearchService(session, models.text_embedder)


def get_image_search_service(session: SessionDep, models: ModelsDep) -> ImageSearchService:
    return ImageSearchService(session, models.image_embedder)


def get_api_key_service(session: SessionDep, hasher: HasherDep) -> ApiKeyService:
    return ApiKeyService(session, hasher)


def get_tenant_service(
    session: SessionDep,
    keys: Annotated[ApiKeyService, Depends(get_api_key_service)],
) -> TenantService:
    return TenantService(session, keys)


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
ImageSearchServiceDep = Annotated[ImageSearchService, Depends(get_image_search_service)]
ApiKeyServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]
TenantServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
