import uuid

from sqlalchemy import ColumnElement, select

from app.db.models import Document
from app.repositories.base import Repository


class DocumentRepository(Repository[Document]):
    async def get(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        return await self._first(Document.tenant_id == tenant_id, Document.id == document_id)

    async def find_by_content_hash(
        self,
        collection_id: uuid.UUID,
        content_hash: str,
    ) -> Document | None:
        return await self._first(
            Document.collection_id == collection_id,
            Document.content_hash == content_hash,
        )

    async def find_by_external_id(
        self,
        collection_id: uuid.UUID,
        external_id: str,
    ) -> Document | None:
        return await self._first(
            Document.collection_id == collection_id,
            Document.external_id == external_id,
        )

    async def _first(self, *conditions: ColumnElement[bool]) -> Document | None:
        document: Document | None = await self.session.scalar(select(Document).where(*conditions))
        return document
