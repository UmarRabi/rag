import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, Select, bindparam, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import TenantRef
from app.db.models import Chunk, Collection, Document, MediaVector
from app.db.models.vectors import IMAGE_EMBEDDING_DIMENSIONS
from app.domain.enums import ChunkModality, MediaType
from app.domain.interfaces import ImageEmbedder
from app.search.service import resolve_collection_ids, tune_vector_scan

if TYPE_CHECKING:
    from PIL.Image import Image


@dataclass(frozen=True, slots=True)
class ImageQuery:
    top_k: int
    candidates: int
    collections: Sequence[str] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    min_score: float | None = None


@dataclass(frozen=True, slots=True)
class ImageHit:
    media_vector_id: int
    document_id: uuid.UUID
    collection: str
    title: str | None
    external_id: str | None
    source_url: str | None
    media_type: MediaType
    page: int | None
    timestamp_ms: int | None
    caption: str | None
    metadata: dict[str, Any]
    score: float


def frame_caption() -> Any:
    return (
        select(Chunk.content)
        .where(
            Chunk.document_id == MediaVector.document_id,
            Chunk.modality == ChunkModality.CAPTION,
            or_(MediaVector.timestamp_ms.is_(None), Chunk.start_ms == MediaVector.timestamp_ms),
        )
        .order_by(Chunk.position)
        .limit(1)
        .correlate(MediaVector)
        .scalar_subquery()
    )


def build_image_search(
    *,
    tenant_id: uuid.UUID,
    collection_ids: Sequence[uuid.UUID] | None,
    filters: Mapping[str, Any],
    vector: Sequence[float],
    candidates: int,
    top_k: int,
    min_score: float | None = None,
) -> Select[Any]:
    query_vector = bindparam("query_vector", list(vector), type_=Vector(IMAGE_EMBEDDING_DIMENSIONS))
    distance = MediaVector.embedding.op("<=>", return_type=Float)(query_vector)
    conditions = [MediaVector.tenant_id == tenant_id]
    if collection_ids is not None:
        conditions.append(MediaVector.collection_id.in_(collection_ids))

    nearest = (
        select(
            MediaVector.id,
            MediaVector.document_id,
            MediaVector.collection_id,
            MediaVector.page,
            MediaVector.timestamp_ms,
            frame_caption().label("caption"),
            distance.label("distance"),
        )
        .where(*conditions)
        .order_by(distance)
        .limit(candidates)
        .subquery("nearest")
    )

    statement = (
        select(
            nearest.c.id.label("media_vector_id"),
            nearest.c.document_id,
            Collection.slug.label("collection"),
            Document.title,
            Document.external_id,
            Document.source_url,
            Document.media_type,
            nearest.c.page,
            nearest.c.timestamp_ms,
            nearest.c.caption,
            Document.meta.label("metadata"),
            (1 - nearest.c.distance).label("score"),
        )
        .select_from(nearest)
        .join(Document, Document.id == nearest.c.document_id)
        .join(Collection, Collection.id == nearest.c.collection_id)
        .order_by(nearest.c.distance, nearest.c.id)
        .limit(top_k)
    )
    if filters:
        statement = statement.where(Document.meta.contains(dict(filters)))
    if min_score is not None:
        statement = statement.where(1 - nearest.c.distance >= min_score)
    return statement


class ImageSearchService:
    def __init__(self, session: AsyncSession, embedder: ImageEmbedder) -> None:
        self._session = session
        self._embedder = embedder

    async def by_text(self, tenant: TenantRef, text: str, query: ImageQuery) -> list[ImageHit]:
        vector = await asyncio.to_thread(self._embedder.embed_text, text)
        return await self._nearest(tenant, vector, query)

    async def by_image(
        self, tenant: TenantRef, image: "Image", query: ImageQuery
    ) -> list[ImageHit]:
        (vector,) = await asyncio.to_thread(self._embedder.embed_images, [image])
        return await self._nearest(tenant, vector, query)

    async def _nearest(
        self,
        tenant: TenantRef,
        vector: Sequence[float],
        query: ImageQuery,
    ) -> list[ImageHit]:
        collection_ids = await resolve_collection_ids(self._session, tenant, query.collections)
        await tune_vector_scan(self._session, query.candidates)
        rows = await self._session.execute(
            build_image_search(
                tenant_id=tenant.id,
                collection_ids=collection_ids,
                filters=query.filters,
                vector=vector,
                candidates=query.candidates,
                top_k=query.top_k,
                min_score=query.min_score,
            ),
        )
        return [ImageHit(**row._asdict()) for row in rows]
