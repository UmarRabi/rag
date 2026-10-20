import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from app.auth.principal import TenantRef
from app.core.errors import NotFoundError, UnsupportedMediaTypeError
from app.core.settings import Settings
from app.db.models import Collection, Document
from app.domain.enums import DocumentStatus, JobKind, SourceType
from app.ingestion.content import (
    Fingerprint,
    IncomingContent,
    fingerprint,
    object_key,
    object_name,
)
from app.pipelines.detection import SNIFF_BYTES, DetectedType, detect
from app.pipelines.registry import ExtractorRegistry
from app.queue.postgres import MEDIA_TYPES, PostgresJobQueue
from app.repositories.collections import CollectionRepository
from app.repositories.documents import DocumentRepository
from app.repositories.storage_connections import StorageConnectionRepository
from app.storage.base import StorageLocation
from app.storage.resolver import ResolvedStorage, StorageResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionRequest:
    collection: str
    content: IncomingContent
    source_type: SourceType
    title: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    document: Document
    duplicate: bool


@dataclass(frozen=True, slots=True)
class StoredOriginal:
    connection_id: uuid.UUID | None
    location: StorageLocation


def stored_original(document: Document) -> StoredOriginal | None:
    if document.storage_uri is None:
        return None
    return StoredOriginal(
        document.storage_connection_id, StorageLocation.parse(document.storage_uri)
    )


async def requeue(session: AsyncSession, document: Document) -> None:
    document.status = DocumentStatus.QUEUED
    document.error = None
    await PostgresJobQueue(session).enqueue(document, JobKind.REPROCESS)


async def requeue_all(session: AsyncSession, tenant_id: uuid.UUID | None = None) -> int:
    conditions: list[ColumnElement[bool]] = [Document.storage_uri.is_not(None)]
    if tenant_id is not None:
        conditions.append(Document.tenant_id == tenant_id)
    documents = (await session.scalars(select(Document).where(*conditions))).all()
    for document in documents:
        await requeue(session, document)
    await session.commit()
    return len(documents)


def describe(
    document: Document,
    *,
    request: IngestionRequest,
    detected: DetectedType,
    content_print: Fingerprint,
) -> None:
    document.title = request.title or request.content.filename
    document.source_type = request.source_type
    document.media_type = detected.media_type
    document.mime_type = detected.mime_type
    document.source_url = request.source_url
    document.size_bytes = content_print.size_bytes
    document.content_hash = content_print.content_hash
    document.meta = request.metadata
    document.status = DocumentStatus.QUEUED
    document.error = None


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        extractors: ExtractorRegistry,
        storage: StorageResolver,
        settings: Settings,
    ) -> None:
        self._session = session
        self._extractors = extractors
        self._storage = storage
        self._settings = settings
        self._collections = CollectionRepository(session)
        self._documents = DocumentRepository(session)
        self._connections = StorageConnectionRepository(session)
        self._queue = PostgresJobQueue(session)

    async def ingest(self, tenant: TenantRef, request: IngestionRequest) -> IngestionOutcome:
        collection = await self._collection(tenant, request.collection)
        content = request.content
        detected = detect(content.head(SNIFF_BYTES), content.declared_mime, content.filename)
        if not self._extractors.supports(detected.media_type):
            raise UnsupportedMediaTypeError(f"{detected.media_type} content is not supported yet")

        content_print = await asyncio.to_thread(
            fingerprint,
            content.stream,
            self._size_limit(detected),
        )
        if duplicate := await self._documents.find_by_content_hash(
            collection.id,
            content_print.content_hash,
        ):
            if duplicate.status is DocumentStatus.FAILED:
                await requeue(self._session, duplicate)
                await self._session.commit()
            return IngestionOutcome(duplicate, duplicate=True)

        existing = await self._existing(collection, request.external_id)
        document = existing or Document(
            id=uuid7(),
            tenant_id=collection.tenant_id,
            collection_id=collection.id,
            external_id=request.external_id,
        )
        replaced = stored_original(existing) if existing else None

        resolved = await self._storage.resolve(await self._connections.for_collection(collection))
        location = await resolved.storage.put(
            object_key(
                tenant_id=collection.tenant_id,
                collection_id=collection.id,
                document_id=document.id,
                content_hash=content_print.content_hash,
                name=object_name(content.filename, detected.mime_type),
            ),
            content.stream,
            detected.mime_type,
        )

        describe(document, request=request, detected=detected, content_print=content_print)
        document.storage_connection_id = resolved.connection_id
        document.storage_uri = location.uri
        if existing is None:
            self._session.add(document)

        try:
            await self._queue.enqueue(document)
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            await self._discard(resolved, location)
            racer = await self._documents.find_by_content_hash(
                collection.id,
                content_print.content_hash,
            )
            if racer is None:
                raise
            return IngestionOutcome(racer, duplicate=True)

        if replaced is not None and replaced.location != location:
            await self.delete_original(replaced)
        return IngestionOutcome(document, duplicate=False)

    async def reprocess(self, tenant: TenantRef, document_id: uuid.UUID) -> Document:
        document = await self._documents.get(tenant.id, document_id)
        if document is None:
            raise NotFoundError("Document not found")
        await requeue(self._session, document)
        await self._session.commit()
        return document

    async def delete(self, tenant: TenantRef, document_id: uuid.UUID) -> None:
        document = await self._documents.get(tenant.id, document_id)
        if document is None:
            raise NotFoundError("Document not found")
        original = stored_original(document)
        await self._session.delete(document)
        await self._session.commit()
        if original is not None:
            await self.delete_original(original)

    async def delete_original(self, original: StoredOriginal) -> None:
        connection = await self._connections.by_id(original.connection_id)
        try:
            storage = await self._storage.for_connection(connection, require_verified=False)
            await storage.delete(original.location)
        except Exception:
            logger.exception("Could not delete stored object %s", original.location.uri)

    async def _collection(self, tenant: TenantRef, slug: str) -> Collection:
        collection = await self._collections.get_by_slug(tenant.id, slug)
        if collection is None:
            raise NotFoundError(f"Collection '{slug}' does not exist")
        return collection

    async def _existing(self, collection: Collection, external_id: str | None) -> Document | None:
        if not external_id:
            return None
        return await self._documents.find_by_external_id(collection.id, external_id)

    def _size_limit(self, detected: DetectedType) -> int:
        if detected.media_type in MEDIA_TYPES:
            return self._settings.max_media_bytes
        return self._settings.max_document_bytes

    @staticmethod
    async def _discard(resolved: ResolvedStorage, location: StorageLocation) -> None:
        try:
            await resolved.storage.delete(location)
        except Exception:
            logger.exception("Could not discard stored object %s", location.uri)
