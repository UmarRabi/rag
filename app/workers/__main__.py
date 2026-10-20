import argparse
import asyncio
import contextlib
import signal

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.domain.enums import JobQueue
from app.infra.database import Database
from app.ml.provider import LocalModels
from app.pipelines.registry import default_registry
from app.storage.crypto import cipher_from_settings
from app.storage.resolver import StorageResolver
from app.workers.worker import Worker


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rag-worker")
    parser.add_argument(
        "--queue", choices=[queue.value for queue in JobQueue], default=JobQueue.LIGHT
    )
    return parser.parse_args()


async def main(queue: JobQueue) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database.from_settings(settings)
    models = LocalModels(settings)
    if settings.preload_models:
        await asyncio.to_thread(models.warm_up)

    worker = Worker(
        database=database,
        models=models,
        extractors=default_registry(models, settings),
        storage=StorageResolver(settings, cipher_from_settings(settings)),
        settings=settings,
        queue=queue,
    )
    stop = asyncio.Event()
    for name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError, AttributeError, ValueError):
            asyncio.get_running_loop().add_signal_handler(getattr(signal, name), stop.set)
    try:
        await worker.run(stop)
    finally:
        await database.dispose()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(JobQueue(arguments().queue)))
