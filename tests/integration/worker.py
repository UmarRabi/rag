from app.core.settings import Settings
from app.domain.enums import JobQueue
from app.domain.interfaces import ModelProvider
from app.infra.database import Database
from app.pipelines.registry import default_registry
from app.storage.crypto import cipher_from_settings
from app.storage.resolver import StorageResolver
from app.workers.worker import Worker


def build_worker(
    settings: Settings,
    models: ModelProvider,
    database: Database,
    queue: JobQueue,
) -> Worker:
    return Worker(
        database=database,
        models=models,
        extractors=default_registry(models, settings),
        storage=StorageResolver(settings, cipher_from_settings(settings)),
        settings=settings,
        queue=queue,
    )


async def run_worker(settings: Settings, models: ModelProvider) -> int:
    database = Database.from_settings(settings)
    workers = [build_worker(settings, models, database, queue) for queue in JobQueue]
    processed = 0
    try:
        for worker in workers:
            while await worker.run_once():
                processed += 1
    finally:
        await database.dispose()
    return processed
