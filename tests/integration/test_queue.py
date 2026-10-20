import asyncio
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid_utils.compat import uuid7

from app.db.models import Document, Job
from app.domain.enums import DocumentStatus, JobQueue, JobStatus, MediaType
from app.queue.postgres import STALE_JOB_ERROR, PostgresJobQueue, queue_for, retry_delay
from tests.integration.factories import make_collection, make_document, make_tenant


async def queued_document(session: AsyncSession, content: str = "Queued content") -> Document:
    collection = await make_collection(session, await make_tenant(session, f"t-{uuid7().hex[:12]}"))
    document = await make_document(session, collection, content)
    await PostgresJobQueue(session).enqueue(document)
    return document


def test_media_goes_to_the_media_queue() -> None:
    assert queue_for(MediaType.AUDIO) is JobQueue.MEDIA
    assert queue_for(MediaType.PDF) is JobQueue.LIGHT


def test_retry_delay_grows_exponentially_and_is_capped() -> None:
    assert [retry_delay(attempt, 10).total_seconds() for attempt in (1, 2, 3)] == [10, 20, 40]
    assert retry_delay(30, 10) == timedelta(hours=1)


async def test_enqueue_replaces_pending_jobs_for_the_document(session: AsyncSession) -> None:
    document = await queued_document(session)
    await PostgresJobQueue(session).enqueue(document)

    jobs = (await session.scalars(select(Job).where(Job.document_id == document.id))).all()
    assert [job.status for job in jobs] == [JobStatus.PENDING]


async def test_claim_marks_the_job_running(session: AsyncSession) -> None:
    await queued_document(session)

    job = await PostgresJobQueue(session).claim(JobQueue.LIGHT, "worker-1")

    assert job is not None
    assert (job.status, job.attempts, job.locked_by) == (JobStatus.RUNNING, 1, "worker-1")
    assert await PostgresJobQueue(session).claim(JobQueue.LIGHT, "worker-2") is None


async def test_concurrent_workers_never_claim_the_same_job(migrated_database: str) -> None:
    engine = create_async_engine(migrated_database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as setup:
            for index in range(5):
                await queued_document(setup, f"Concurrent content {index}")
            await setup.commit()

        async def claim(worker: str) -> Job | None:
            async with sessions() as session:
                return await PostgresJobQueue(session).claim(JobQueue.LIGHT, worker)

        claimed = await asyncio.gather(*(claim(f"worker-{index}") for index in range(8)))
        ids = [job.id for job in claimed if job is not None]

        assert len(ids) == len(set(ids)) == 5
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(text("TRUNCATE tenants CASCADE"))
            await cleanup.commit()
        await engine.dispose()


async def test_stale_jobs_are_released_or_failed_when_out_of_attempts(
    session: AsyncSession,
) -> None:
    retryable = await queued_document(session, "Retryable")
    exhausted = await queued_document(session, "Exhausted")
    await session.execute(
        text(
            "UPDATE jobs SET status = 'running', locked_at = now() - interval '1 hour', "
            "attempts = CASE WHEN document_id = :exhausted THEN max_attempts ELSE 1 END",
        ),
        {"exhausted": exhausted.id},
    )

    released = await PostgresJobQueue(session).release_stale(JobQueue.LIGHT, timedelta(minutes=15))

    statuses = {
        document_id: status
        for document_id, status in await session.execute(select(Job.document_id, Job.status))
    }
    await session.refresh(exhausted)
    assert released == 2
    assert statuses == {retryable.id: JobStatus.PENDING, exhausted.id: JobStatus.FAILED}
    assert (exhausted.status, exhausted.error) == (DocumentStatus.FAILED, STALE_JOB_ERROR)
