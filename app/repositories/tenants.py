from collections.abc import Sequence

from sqlalchemy import select

from app.db.models import Tenant
from app.repositories.base import Repository


class TenantRepository(Repository[Tenant]):
    async def get_by_slug(self, slug: str) -> Tenant | None:
        tenant: Tenant | None = await self.session.scalar(select(Tenant).where(Tenant.slug == slug))
        return tenant

    async def list_all(self) -> Sequence[Tenant]:
        result = await self.session.scalars(select(Tenant).order_by(Tenant.slug))
        return result.all()
