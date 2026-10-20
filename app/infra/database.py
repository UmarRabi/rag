from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        engine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
        )
        return cls(engine)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


async def extension_version(session: AsyncSession, name: str) -> str | None:
    result = await session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = :name"),
        {"name": name},
    )
    return result.scalar_one_or_none()
