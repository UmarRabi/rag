import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.db.models import Collection
from app.repositories.base import Repository


class CollectionRepository(Repository[Collection]):
    async def get_by_slug(self, tenant_id: uuid.UUID, slug: str) -> Collection | None:
        collection: Collection | None = await self.session.scalar(
            select(Collection).where(Collection.tenant_id == tenant_id, Collection.slug == slug),
        )
        return collection

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[Collection]:
        result = await self.session.scalars(
            select(Collection).where(Collection.tenant_id == tenant_id).order_by(Collection.name),
        )
        return result.all()
