import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.keys import ApiKeyToken, KeyHasher
from app.auth.principal import Principal
from app.core.errors import UnauthorizedError
from app.db.models import ApiKey, Tenant
from app.domain.enums import TenantStatus

INVALID_KEY = "Invalid, expired or revoked API key"
MAX_CACHED_KEYS = 10_000


@dataclass(frozen=True, slots=True)
class CachedKey:
    principal: Principal
    digest: str
    cached_at: float


class Authenticator:
    def __init__(
        self,
        hasher: KeyHasher,
        *,
        cache_seconds: float,
        touch_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._hasher = hasher
        self._cache_seconds = cache_seconds
        self._touch_seconds = touch_seconds
        self._clock = clock
        self._cache: dict[str, CachedKey] = {}
        self._touched: dict[uuid.UUID, float] = {}

    async def authenticate(self, session: AsyncSession, token: str) -> Principal:
        presented = ApiKeyToken.parse(token)
        if presented is None:
            raise UnauthorizedError(INVALID_KEY)

        cached = self._fresh(presented.prefix) or await self._load(session, presented.prefix)
        if not self._hasher.matches(presented.secret, cached.digest):
            raise UnauthorizedError(INVALID_KEY)
        if cached.principal.expired:
            self.forget(prefix=presented.prefix)
            raise UnauthorizedError(INVALID_KEY)

        await self._touch(session, cached.principal.key_id)
        return cached.principal

    def forget(self, *, prefix: str | None = None, tenant_id: uuid.UUID | None = None) -> None:
        stale = [
            key
            for key, cached in self._cache.items()
            if key == prefix or cached.principal.tenant.id == tenant_id
        ]
        for key in stale:
            del self._cache[key]

    def _fresh(self, prefix: str) -> CachedKey | None:
        cached = self._cache.get(prefix)
        if cached is None or self._clock() - cached.cached_at > self._cache_seconds:
            return None
        return cached

    async def _load(self, session: AsyncSession, prefix: str) -> CachedKey:
        result = await session.execute(
            select(ApiKey, Tenant)
            .join(Tenant, Tenant.id == ApiKey.tenant_id)
            .where(ApiKey.prefix == prefix),
        )
        row = result.first()
        if row is None:
            raise UnauthorizedError(INVALID_KEY)

        key, tenant = row
        if key.revoked_at is not None or tenant.status != TenantStatus.ACTIVE:
            raise UnauthorizedError(INVALID_KEY)

        if len(self._cache) >= MAX_CACHED_KEYS:
            self._cache.clear()
        cached = CachedKey(Principal.of(key, tenant), key.key_hash, self._clock())
        self._cache[prefix] = cached
        return cached

    async def _touch(self, session: AsyncSession, key_id: uuid.UUID) -> None:
        now = self._clock()
        last = self._touched.get(key_id)
        if last is not None and now - last < self._touch_seconds:
            return
        self._touched[key_id] = now
        await session.execute(
            update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=func.now()),
        )
        await session.commit()
