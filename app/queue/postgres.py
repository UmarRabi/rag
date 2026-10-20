from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Job
from app.domain.enums import DocumentStatus, JobKind, JobQueue, JobStatus, MediaType

MEDIA_TYPES = frozenset({MediaType.IMAGE, MediaType.AUDIO, MediaType.VIDEO})
MAX_RETRY_DELAY = timedelta(hours=1)
STALE_JOB_ERROR = "Processing stopped responding and ran out of retries"


def queue_for(media_type: MediaType) -> JobQueue:
    return JobQueue.MEDIA if media_type in MEDIA_TYPES else JobQueue.LIGHT


def retry_delay(attempt: int, base_seconds: int) -> timedelta:
    return min(timedelta(seconds=base_seconds * 2 ** (attempt - 1)), MAX_RETRY_DELAY)


class PostgresJobQueue:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, document: Document, kind: JobKind = JobKind.INGEST) -> Job:
        await self._session.execute(
            delete(Job).where(Job.document_id == document.id, Job.status == JobStatus.PENDING),
        )
        job = Job(
            tenant_id=document.tenant_id,
            document_id=document.id,
            kind=kind,
            queue=queue_for(document.media_type),
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def claim(self, queue: JobQueue, worker_id: str) -> Job | None:
        next_job = (
            select(Job.id)
            .where(
                Job.queue == queue,
                Job.status == JobStatus.PENDING,
                Job.run_after <= func.now(),
            )
            .order_by(Job.priority.desc(), Job.run_after)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        job: Job | None = await self._session.scalar(
            update(Job)
            .where(Job.id == next_job)
            .values(
                status=JobStatus.RUNNING,
                locked_by=worker_id,
                locked_at=func.now(),
                attempts=Job.attempts + 1,
            )
            .returning(Job),
        )
        await self._session.commit()
        return job

    async def complete(self, job: Job) -> None:
        job.status = JobStatus.SUCCEEDED
        job.locked_by = None
        job.last_error = None
        await self._session.commit()

    async def retry_or_fail(
        self,
        job: Job,
        error: str,
        base_delay_seconds: int,
        *,
        permanent: bool = False,
    ) -> bool:
        retrying = not permanent and job.attempts < job.max_attempts
        job.status = JobStatus.PENDING if retrying else JobStatus.FAILED
        job.locked_by = None
        job.last_error = error
        if retrying:
            job.run_after = func.now() + retry_delay(job.attempts, base_delay_seconds)
        await self._session.commit()
        return retrying

    async def release_stale(self, queue: JobQueue, older_than: timedelta) -> int:
        stale = (
            Job.queue == queue,
            Job.status == JobStatus.RUNNING,
            Job.locked_at < func.now() - older_than,
        )
        exhausted = await self._session.scalars(
            update(Job)
            .where(*stale, Job.attempts >= Job.max_attempts)
            .values(status=JobStatus.FAILED, locked_by=None, last_error=STALE_JOB_ERROR)
            .returning(Job.document_id),
        )
        if failed_documents := exhausted.all():
            await self._session.execute(
                update(Document)
                .where(Document.id.in_(failed_documents))
                .values(status=DocumentStatus.FAILED, error=STALE_JOB_ERROR),
            )
        released = await self._session.scalars(
            update(Job)
            .where(*stale)
            .values(status=JobStatus.PENDING, locked_by=None, run_after=func.now())
            .returning(Job.id),
        )
        count = len(released.all()) + len(failed_documents)
        await self._session.commit()
        return count
