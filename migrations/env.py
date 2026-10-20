import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.settings import get_settings
from app.db.models import Base

ischema_names["regconfig"] = REGCONFIG

config = context.config

if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def database_url() -> str:
    url: str = config.attributes.get("database_url") or get_settings().database_url
    return url


def configure_context(**options: object) -> None:
    context.configure(target_metadata=Base.metadata, compare_type=True, **options)


def run_migrations(connection: Connection) -> None:
    configure_context(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


def run_offline() -> None:
    configure_context(url=database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
