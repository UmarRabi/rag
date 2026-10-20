import uuid
from collections.abc import Sequence

from sqlalchemy import exists, or_, select

from app.db.models import Collection, Document, StorageConnection
from app.repositories.base import Repository


class StorageConnectionRepository(Repository[StorageConnection]):
    async def get(self, tenant_id: uuid.UUID, connection_id: uuid.UUID) -> StorageConnection | None:
        connection: StorageConnection | None = await self.session.scalar(
            select(StorageConnection).where(
                StorageConnection.tenant_id == tenant_id,
                StorageConnection.id == connection_id,
            ),
        )
        return connection

    async def by_id(self, connection_id: uuid.UUID | None) -> StorageConnection | None:
        if connection_id is None:
            return None
        return await self.session.get(StorageConnection, connection_id)

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> Sequence[StorageConnection]:
        result = await self.session.scalars(
            select(StorageConnection)
            .where(StorageConnection.tenant_id == tenant_id)
            .order_by(StorageConnection.name),
        )
        return result.all()

    async def for_collection(self, collection: Collection) -> StorageConnection | None:
        if collection.storage_connection_id is not None:
            return await self.by_id(collection.storage_connection_id)
        default: StorageConnection | None = await self.session.scalar(
            select(StorageConnection).where(
                StorageConnection.tenant_id == collection.tenant_id,
                StorageConnection.is_default,
            ),
        )
        return default

    async def in_use(self, connection: StorageConnection) -> bool:
        used = await self.session.scalar(
            select(
                or_(
                    exists().where(Collection.storage_connection_id == connection.id),
                    exists().where(Document.storage_connection_id == connection.id),
                ),
            ),
        )
        return bool(used)
