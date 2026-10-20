import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.keys import ApiKeyToken, KeyHasher
from app.core.errors import ConflictError, NotFoundError
from app.db.models import ApiKey, Tenant
from app.domain.enums import ApiKeyScope
from app.repositories.api_keys import ApiKeyRepository
from app.repositories.tenants import TenantRepository

BOOTSTRAP_KEY_NAME = "Initial admin key"


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    key: ApiKey
    token: str


@dataclass(frozen=True, slots=True)
class CreatedTenant:
    tenant: Tenant
    admin_key: IssuedApiKey


class ApiKeyService:
    def __init__(self, session: AsyncSession, hasher: KeyHasher) -> None:
        self._session = session
        self._hasher = hasher
        self._keys = ApiKeyRepository(session)

    async def issue(
        self,
        tenant_id: uuid.UUID,
        name: str,
        scopes: Iterable[ApiKeyScope],
        expires_at: datetime | None = None,
    ) -> IssuedApiKey:
        token = ApiKeyToken.issue()
        key = await self._keys.add(
            ApiKey(
                tenant_id=tenant_id,
                name=name,
                prefix=token.prefix,
                key_hash=self._hasher.digest(token.secret),
                scopes=sorted({ApiKeyScope(scope).value for scope in scopes}),
                expires_at=expires_at,
            ),
        )
        await self._session.commit()
        return IssuedApiKey(key, token.value)

    async def list(self, tenant_id: uuid.UUID) -> Sequence[ApiKey]:
        return await self._keys.list_for_tenant(tenant_id)

    async def revoke(self, tenant_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey:
        key = await self._keys.get(tenant_id, key_id)
        if key is None:
            raise NotFoundError("API key not found")
        if key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
            await self._session.commit()
        return key


class TenantService:
    def __init__(self, session: AsyncSession, keys: ApiKeyService) -> None:
        self.session = session
        self._keys = keys
        self._tenants = TenantRepository(session)

    async def create(self, slug: str, name: str, settings: dict[str, Any]) -> CreatedTenant:
        tenant = Tenant(slug=slug, name=name, settings=settings)
        try:
            await self._tenants.add(tenant)
        except IntegrityError as error:
            raise ConflictError(f"Tenant '{slug}' already exists") from error
        admin_key = await self._keys.issue(tenant.id, BOOTSTRAP_KEY_NAME, [ApiKeyScope.ADMIN])
        return CreatedTenant(tenant, admin_key)

    async def get(self, slug: str) -> Tenant:
        tenant = await self._tenants.get_by_slug(slug)
        if tenant is None:
            raise NotFoundError(f"Tenant '{slug}' does not exist")
        return tenant

    async def list(self) -> Sequence[Tenant]:
        return await self._tenants.list_all()

    async def update(self, slug: str, changes: dict[str, Any]) -> Tenant:
        tenant = await self.get(slug)
        for name, value in changes.items():
            setattr(tenant, name, value)
        await self.session.commit()
        return tenant
