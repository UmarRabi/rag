import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self

from app.db.models import ApiKey, Tenant
from app.domain.enums import ApiKeyScope


@dataclass(frozen=True, slots=True)
class TenantRef:
    id: uuid.UUID
    slug: str
    settings: Mapping[str, Any]

    @classmethod
    def of(cls, tenant: Tenant) -> Self:
        return cls(tenant.id, tenant.slug, dict(tenant.settings))


@dataclass(frozen=True, slots=True)
class Principal:
    key_id: uuid.UUID
    key_prefix: str
    tenant: TenantRef
    scopes: frozenset[ApiKeyScope]
    expires_at: datetime | None

    @classmethod
    def of(cls, key: ApiKey, tenant: Tenant) -> Self:
        return cls(
            key_id=key.id,
            key_prefix=key.prefix,
            tenant=TenantRef.of(tenant),
            scopes=frozenset(ApiKeyScope(scope) for scope in key.scopes),
            expires_at=key.expires_at,
        )

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(UTC)
