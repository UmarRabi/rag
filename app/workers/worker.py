import asyncio
import contextlib
import logging
import socket
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidContentError
from app.core.settings import Settings
from app.db.models import Document, Job
from app.domain.enums import JobQueue
from app.domain.interfaces import ModelProvider
from app.infra.database import Database
from app.ingestion.chunking import Chunker, ChunkingPolicy
from app.ingestion.processor import DocumentProcessor
from app.pipelines.registry import ExtractorRegistry
from app.queue.postgres import PostgresJobQueue
from app.storage.resolver import StorageResolver

logger = logging.getLogger(__name__)

STALE_SWEEP_SECONDS = 60


def worker_name(queue: JobQueue) -> str:
    return f"{socket.gethostname()}:{queue}:{uuid.uuid4().hex[:8]}"


class Worker:
    def __init__(
        self,
        *,
        database: Database,
        models: ModelProvider,
        extractors: ExtractorRegistry,
        storage: StorageResolver,
        settings: Settings,
        queue: JobQueue,
    ) -> None:
        self._database = database
        self._models = models
        self._extractors = extractors
        self._storage = storage
        self._settings = settings
        self._queue = queue
        self._policy = ChunkingPolicy(settings.chunk_max_tokens, settings.chunk_overlap_tokens)
        self.name = worker_name(queue)

    async def run(self, stop: asyncio.Event) -> None:
        logger.info("Worker %s started with %d slots", self.name, self._settings.worker_concurrency)
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._sweep_stale(stop))
            for _ in range(self._settings.worker_concurrency):
                tasks.create_task(self._work(stop))
        logger.info("Worker %s stopped", self.name)

    async def run_once(self) -> bool:
        async with self._database.session() as session:
            job = await PostgresJobQueue(session).claim(self._queue, self.name)
            if job is None:
                return False
            await self._handle(session, job)
        return True

    async def release_stale(self) -> int:
        async with self._database.session() as session:
            return await PostgresJobQueue(session).release_stale(
                self._queue,
                timedelta(seconds=self._settings.worker_stale_after_seconds),
            )

    async def _work(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                logger.exception("Worker %s could not claim a job", self.name)
                processed = False
            if not processed:
                await self._pause(stop, self._settings.worker_idle_seconds)

    async def _sweep_stale(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                if released := await self.release_stale():
                    logger.warning("Released %d stale jobs", released)
            except Exception:
                logger.exception("Stale job sweep failed")
            await self._pause(stop, STALE_SWEEP_SECONDS)

    async def _handle(self, session: AsyncSession, job: Job) -> None:
        queue = PostgresJobQueue(session)
        document = await session.get(Document, job.document_id)
        if document is None:
            await queue.complete(job)
            return

        processor = DocumentProcessor(
            session,
            self._models,
            self._extractors,
            Chunker(self._models.token_counter, self._policy),
            self._storage,
        )
        try:
            await processor.process(document)
        except Exception as error:
            logger.exception("Job %s failed on attempt %d", job.id, job.attempts)
            await session.rollback()
            await session.refresh(job)
            await session.refresh(document)
            message = str(error) or type(error).__name__
            retrying = await queue.retry_or_fail(
                job,
                message,
                self._settings.job_retry_base_seconds,
                permanent=isinstance(error, InvalidContentError),
            )
            await processor.record_failure(document, message, retrying=retrying)
            return

        await queue.complete(job)

    @staticmethod
    async def _pause(stop: asyncio.Event, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
