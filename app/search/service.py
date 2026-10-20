import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import TenantRef
from app.core.errors import NotFoundError
from app.db.models import Collection
from app.domain.enums import ChunkModality, MediaType, SearchMode
from app.domain.interfaces import TextEmbedder
from app.search.queries import SearchScope, build_search

HNSW_MIN_EF_SEARCH = 40
HNSW_MAX_EF_SEARCH = 1000


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    top_k: int
    candidates: int
    mode: SearchMode = SearchMode.HYBRID
    collections: Sequence[str] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    modalities: Sequence[ChunkModality] = ()
    min_score: float | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: int
    document_id: uuid.UUID
    collection: str
    title: str | None
    external_id: str | None
    source_url: str | None
    media_type: MediaType
    content: str
    modality: ChunkModality
    page: int | None
    start_ms: int | None
    end_ms: int | None
    language: str | None
    metadata: dict[str, Any]
    score: float
    vector_score: float | None
    keyword_score: float | None


async def resolve_collection_ids(
    session: AsyncSession,
    tenant: TenantRef,
    slugs: Sequence[str],
) -> list[uuid.UUID] | None:
    if not slugs:
        return None
    wanted = set(slugs)
    rows = await session.execute(
        select(Collection.slug, Collection.id).where(
            Collection.tenant_id == tenant.id,
            Collection.slug.in_(wanted),
        ),
    )
    found = {slug: collection_id for slug, collection_id in rows}
    if missing := sorted(wanted - found.keys()):
        raise NotFoundError(f"Unknown collections: {', '.join(missing)}")
    return list(found.values())


async def tune_vector_scan(session: AsyncSession, candidates: int) -> None:
    ef_search = min(max(candidates, HNSW_MIN_EF_SEARCH), HNSW_MAX_EF_SEARCH)
    await session.execute(
        select(
            func.set_config("hnsw.ef_search", str(ef_search), True),
            func.set_config("hnsw.iterative_scan", "relaxed_order", True),
        ),
    )


class SearchService:
    def __init__(self, session: AsyncSession, embedder: TextEmbedder) -> None:
        self._session = session
        self._embedder = embedder

    async def search(self, tenant: TenantRef, query: SearchQuery) -> list[SearchHit]:
        scope = SearchScope(
            tenant_id=tenant.id,
            collection_ids=await resolve_collection_ids(self._session, tenant, query.collections),
            filters=query.filters,
            modalities=query.modalities,
        )
        vector = await self._query_vector(query)
        if vector is not None:
            await tune_vector_scan(self._session, query.candidates)

        statement = build_search(
            scope=scope,
            mode=query.mode,
            text=query.text,
            vector=vector,
            candidates=query.candidates,
            top_k=query.top_k,
            min_score=query.min_score,
        )
        rows = await self._session.execute(statement)
        return [SearchHit(**row._asdict()) for row in rows]

    async def _query_vector(self, query: SearchQuery) -> list[float] | None:
        if query.mode is SearchMode.KEYWORD:
            return None
        return await asyncio.to_thread(self._embedder.embed_query, query.text)
