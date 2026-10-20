import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CTE,
    BindParameter,
    ColumnElement,
    Float,
    Select,
    Text,
    bindparam,
    cast,
    func,
    literal_column,
    null,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import TSQUERY

from app.db.models import Chunk, Collection, Document
from app.db.models.vectors import TEXT_EMBEDDING_DIMENSIONS
from app.domain.enums import ChunkModality, SearchMode
from app.ingestion.language import SIMPLE_TEXT_SEARCH_CONFIG, TEXT_SEARCH_CONFIGS

RRF_K = 60
MAX_RRF_SCORE = 2 / (RRF_K + 1)
SEARCH_CONFIGS = sorted({*TEXT_SEARCH_CONFIGS.values(), SIMPLE_TEXT_SEARCH_CONFIG})


@dataclass(frozen=True, slots=True)
class SearchScope:
    tenant_id: uuid.UUID
    collection_ids: Sequence[uuid.UUID] | None
    filters: Mapping[str, Any]
    modalities: Sequence[ChunkModality]

    def conditions(self) -> list[ColumnElement[bool]]:
        conditions = [Chunk.tenant_id == self.tenant_id]
        if self.collection_ids is not None:
            conditions.append(Chunk.collection_id.in_(self.collection_ids))
        if self.filters:
            conditions.append(Chunk.meta.contains(dict(self.filters)))
        if self.modalities:
            conditions.append(Chunk.modality.in_(self.modalities))
        return conditions


def ranked(name: str, hits: Select[Any], *, descending: bool) -> CTE:
    inner = hits.subquery()
    order = inner.c.order_key.desc() if descending else inner.c.order_key
    return select(
        inner.c.chunk_id,
        inner.c.score,
        func.row_number().over(order_by=order).label("rank"),
    ).cte(name)


def vector_hits(scope: SearchScope, vector: Sequence[float], limit: int) -> CTE:
    query_vector = bindparam("query_vector", list(vector), type_=Vector(TEXT_EMBEDDING_DIMENSIONS))
    distance = Chunk.embedding.op("<=>", return_type=Float)(query_vector)
    hits = (
        select(
            Chunk.id.label("chunk_id"),
            (1 - distance).label("score"),
            distance.label("order_key"),
        )
        .where(*scope.conditions())
        .order_by(distance)
        .limit(limit)
    )
    return ranked("vector_hits", hits, descending=False)


def any_term_query(config: str, text: BindParameter[str]) -> ColumnElement[Any]:
    terms = func.plainto_tsquery(literal_column(f"'{config}'::regconfig"), text)
    return cast(func.replace(cast(terms, Text), "&", "|"), TSQUERY)


def multilingual_query(text: str) -> ColumnElement[Any]:
    query_text = bindparam("query_text", text, type_=Text)
    queries = [any_term_query(config, query_text) for config in SEARCH_CONFIGS]
    return reduce(lambda left, right: left.op("||")(right), queries)


def keyword_hits(scope: SearchScope, text: str, limit: int) -> CTE:
    terms = select(multilingual_query(text).label("query")).cte("search_terms")
    rank = func.ts_rank_cd(Chunk.search_vector, terms.c.query)
    hits = (
        select(Chunk.id.label("chunk_id"), rank.label("score"), rank.label("order_key"))
        .select_from(Chunk)
        .join(terms, true())
        .where(*scope.conditions(), Chunk.search_vector.op("@@")(terms.c.query))
        .order_by(rank.desc())
        .limit(limit)
    )
    return ranked("keyword_hits", hits, descending=True)


def reciprocal_rank(rank: ColumnElement[Any]) -> ColumnElement[float]:
    return func.coalesce(cast(1.0, Float) / (RRF_K + rank), 0.0)


def fused(vector: CTE | None, keyword: CTE | None) -> Select[Any]:
    if vector is not None and keyword is not None:
        score = (reciprocal_rank(vector.c.rank) + reciprocal_rank(keyword.c.rank)) / MAX_RRF_SCORE
        return select(
            func.coalesce(vector.c.chunk_id, keyword.c.chunk_id).label("chunk_id"),
            score.label("score"),
            vector.c.score.label("vector_score"),
            keyword.c.score.label("keyword_score"),
        ).select_from(vector.join(keyword, vector.c.chunk_id == keyword.c.chunk_id, full=True))

    if vector is not None:
        return select(
            vector.c.chunk_id,
            vector.c.score,
            vector.c.score.label("vector_score"),
            null().label("keyword_score"),
        )

    if keyword is not None:
        return select(
            keyword.c.chunk_id,
            keyword.c.score,
            null().label("vector_score"),
            keyword.c.score.label("keyword_score"),
        )

    raise ValueError("A search needs at least one ranking")


def build_search(
    *,
    scope: SearchScope,
    mode: SearchMode,
    text: str,
    vector: Sequence[float] | None,
    candidates: int,
    top_k: int,
    min_score: float | None = None,
) -> Select[Any]:
    vector_ranking = (
        vector_hits(scope, vector, candidates)
        if vector is not None and mode is not SearchMode.KEYWORD
        else None
    )
    keyword_ranking = (
        keyword_hits(scope, text, candidates) if mode is not SearchMode.VECTOR else None
    )
    results = fused(vector_ranking, keyword_ranking).subquery("results")
    threshold = results.c.vector_score if mode is SearchMode.HYBRID else results.c.score

    statement = (
        select(
            results.c.score,
            results.c.vector_score,
            results.c.keyword_score,
            Chunk.id.label("chunk_id"),
            Chunk.document_id,
            Chunk.content,
            Chunk.modality,
            Chunk.page,
            Chunk.start_ms,
            Chunk.end_ms,
            Chunk.language,
            Chunk.meta.label("metadata"),
            Document.title,
            Document.external_id,
            Document.source_url,
            Document.media_type,
            Collection.slug.label("collection"),
        )
        .select_from(results)
        .join(Chunk, Chunk.id == results.c.chunk_id)
        .join(Document, Document.id == Chunk.document_id)
        .join(Collection, Collection.id == Chunk.collection_id)
        .order_by(results.c.score.desc(), Chunk.id)
        .limit(top_k)
    )
    if min_score is not None:
        statement = statement.where(threshold >= min_score)
    return statement
