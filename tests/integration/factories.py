import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Collection, Document, StorageConnection, Tenant
from app.db.models.vectors import TEXT_EMBEDDING_DIMENSIONS
from app.domain.enums import (
    ChunkModality,
    MediaType,
    SourceType,
    StorageAuthType,
    StorageProvider,
)


async def persist[T](session: AsyncSession, entity: T) -> T:
    session.add(entity)
    await session.flush()
    return entity


async def make_tenant(session: AsyncSession, slug: str = "acme") -> Tenant:
    return await persist(session, Tenant(name=slug.title(), slug=slug))


async def make_collection(
    session: AsyncSession,
    tenant: Tenant,
    slug: str = "support",
) -> Collection:
    return await persist(session, Collection(tenant_id=tenant.id, name=slug.title(), slug=slug))


async def make_document(
    session: AsyncSession,
    collection: Collection,
    content: str = "How to reset your password",
    **overrides: Any,
) -> Document:
    fields: dict[str, Any] = {
        "tenant_id": collection.tenant_id,
        "collection_id": collection.id,
        "source_type": SourceType.TEXT,
        "media_type": MediaType.TEXT,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
    }
    return await persist(session, Document(**(fields | overrides)))


async def make_chunk(
    session: AsyncSession,
    document: Document,
    content: str,
    **overrides: Any,
) -> Chunk:
    fields: dict[str, Any] = {
        "tenant_id": document.tenant_id,
        "collection_id": document.collection_id,
        "document_id": document.id,
        "position": 0,
        "modality": ChunkModality.TEXT,
        "content": content,
        "token_count": len(content.split()),
        "embedding": [0.1] * TEXT_EMBEDDING_DIMENSIONS,
        "embedding_model": "intfloat/multilingual-e5-base",
    }
    return await persist(session, Chunk(**(fields | overrides)))


def storage_connection(tenant: Tenant, **overrides: Any) -> StorageConnection:
    fields: dict[str, Any] = {
        "tenant_id": tenant.id,
        "name": "Primary bucket",
        "provider": StorageProvider.S3,
        "bucket": "acme-rag",
        "auth_type": StorageAuthType.ASSUME_ROLE,
        "role_arn": "arn:aws:iam::123456789012:role/rag-access",
    }
    return StorageConnection(**(fields | overrides))
