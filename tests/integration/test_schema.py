from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED_TABLES = {
    "alembic_version",
    "tenants",
    "api_keys",
    "storage_connections",
    "collections",
    "documents",
    "chunks",
    "media_vectors",
    "jobs",
}


async def index_definition(session: AsyncSession, name: str) -> str:
    definition: str = await session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
        {"name": name},
    )
    return definition


async def test_creates_every_table(session: AsyncSession) -> None:
    result = await session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
    )

    assert set(result.scalars()) == EXPECTED_TABLES


async def test_vector_columns_use_cosine_hnsw(session: AsyncSession) -> None:
    for name in ("ix_chunks_embedding", "ix_media_vectors_embedding"):
        definition = await index_definition(session, name)

        assert "USING hnsw" in definition
        assert "vector_cosine_ops" in definition


async def test_keyword_and_metadata_indexes_use_gin(session: AsyncSession) -> None:
    for name in ("ix_chunks_search_vector", "ix_chunks_metadata"):
        assert "USING gin" in await index_definition(session, name)


async def test_pending_jobs_index_is_partial(session: AsyncSession) -> None:
    definition = await index_definition(session, "ix_jobs_pending")

    assert "priority DESC" in definition
    assert "WHERE" in definition


def test_models_match_migrations(migrated_database: str, alembic_config: Config) -> None:
    command.check(alembic_config)


def test_migrations_round_trip(migrated_database: str, alembic_config: Config) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
