import asyncio
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidContentError, ServiceError
from app.db.models import Document
from app.domain.content import ChunkDraft, Extraction, Frame, RawContent
from app.domain.enums import DocumentStatus
from app.domain.interfaces import ModelProvider
from app.ingestion.chunking import Chunker
from app.ingestion.language import dominant_language, text_search_config
from app.pipelines.registry import ExtractorRegistry
from app.repositories.chunks import ChunkRepository
from app.repositories.media_vectors import MediaVectorRepository
from app.repositories.storage_connections import StorageConnectionRepository
from app.storage.base import StorageLocation
from app.storage.resolver import StorageResolver


class DocumentProcessor:
    def __init__(
        self,
        session: AsyncSession,
        models: ModelProvider,
        extractors: ExtractorRegistry,
        chunker: Chunker,
        storage: StorageResolver,
    ) -> None:
        self._session = session
        self._models = models
        self._extractors = extractors
        self._chunker = chunker
        self._storage = storage
        self._chunks = ChunkRepository(session)
        self._media_vectors = MediaVectorRepository(session)
        self._connections = StorageConnectionRepository(session)

    async def process(self, document: Document) -> None:
        document.status = DocumentStatus.PROCESSING
        await self._session.commit()

        extraction = await self._extract(document, await self._original(document))
        drafts = self._chunker.split(extraction.segments)
        if not drafts and not extraction.frames:
            raise InvalidContentError("No text could be extracted from the content")

        languages, embeddings = await self._enrich([draft.content for draft in drafts])
        embedding_model = self._models.text_embedder.model_name
        rows = [
            chunk_row(
                document=document,
                position=position,
                draft=draft,
                language=language,
                embedding=embedding,
                embedding_model=embedding_model,
            )
            for position, (draft, language, embedding) in enumerate(
                zip(drafts, languages, embeddings, strict=True),
            )
        ]
        await self._chunks.replace_for_document(document, rows)
        await self._media_vectors.replace_for_document(
            document,
            await self._frame_rows(document, extraction.frames),
        )

        document.status = DocumentStatus.READY
        document.error = None
        document.chunk_count = len(rows)
        document.language = dominant_language(languages)
        document.duration_ms = extraction.duration_ms or document.duration_ms
        document.processed_at = datetime.now(UTC)
        await self._session.commit()

    async def record_failure(self, document: Document, error: str, *, retrying: bool) -> None:
        document.status = DocumentStatus.QUEUED if retrying else DocumentStatus.FAILED
        document.error = error
        await self._session.commit()

    async def _original(self, document: Document) -> RawContent:
        if document.storage_uri is None:
            raise InvalidContentError("Document has no stored content")
        location = StorageLocation.parse(document.storage_uri)
        connection = await self._connections.by_id(document.storage_connection_id)
        storage = await self._storage.for_connection(connection, require_verified=False)
        return RawContent(
            data=await storage.get(location),
            mime_type=document.mime_type or "application/octet-stream",
            filename=PurePosixPath(location.key).name,
        )

    async def _extract(self, document: Document, content: RawContent) -> Extraction:
        extractor = self._extractors.get(document.media_type)
        try:
            return await asyncio.to_thread(extractor.extract, content)
        except ServiceError:
            raise
        except Exception as error:
            raise InvalidContentError(
                f"Could not read {document.media_type} content: {error}"
            ) from error

    async def _enrich(self, texts: list[str]) -> tuple[list[str | None], list[list[float]]]:
        if not texts:
            return [], []
        detector = self._models.language_detector
        return await asyncio.gather(
            asyncio.to_thread(lambda: [detector.detect(text) for text in texts]),
            asyncio.to_thread(self._models.text_embedder.embed_passages, texts),
        )

    async def _frame_rows(self, document: Document, frames: list[Frame]) -> list[dict[str, Any]]:
        if not frames:
            return []
        embedder = self._models.image_embedder
        vectors = await asyncio.to_thread(embedder.embed_images, [frame.image for frame in frames])
        return [
            {
                "tenant_id": document.tenant_id,
                "collection_id": document.collection_id,
                "document_id": document.id,
                "position": position,
                "page": frame.page,
                "timestamp_ms": frame.timestamp_ms,
                "embedding": vector,
                "embedding_model": embedder.model_name,
            }
            for position, (frame, vector) in enumerate(zip(frames, vectors, strict=True))
        ]


def chunk_row(
    *,
    document: Document,
    position: int,
    draft: ChunkDraft,
    language: str | None,
    embedding: list[float],
    embedding_model: str,
) -> dict[str, Any]:
    return {
        "tenant_id": document.tenant_id,
        "collection_id": document.collection_id,
        "document_id": document.id,
        "position": position,
        "modality": draft.segment.modality,
        "content": draft.content,
        "token_count": draft.token_count,
        "language": language,
        "text_search_config": text_search_config(language),
        "page": draft.segment.page,
        "start_ms": draft.segment.start_ms,
        "end_ms": draft.segment.end_ms,
        "meta": document.meta,
        "embedding": embedding,
        "embedding_model": embedding_model,
    }
