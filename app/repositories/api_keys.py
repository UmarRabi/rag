import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.db.models import ApiKey
from app.repositories.base import Repository


class ApiKeyRepository(Repository[ApiKey]):
    async def get(self, tenant_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        key: ApiKey | None = await self.session.scalar(
            select(ApiKey).where(ApiKey.tenant_id == tenant_id, ApiKey.id == key_id),
        )
        return key

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[ApiKey]:
        result = await self.session.scalars(
            select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at),
        )
        return result.all()
