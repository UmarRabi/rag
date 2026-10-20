import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fakeredis import FakeAsyncRedis as FakeRedis
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import make_url, pool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.dependencies import get_models
from app.auth.rate_limit import RedisRateLimiter
from app.core.settings import Settings, get_settings
from app.domain.interfaces import ModelProvider
from app.main import create_app
from tests.fakes import FakeModels
from tests.integration.client import (
    PLATFORM_ADMIN_KEY,
    PLATFORM_BUCKET,
    SMALL_CHUNKS,
    TENANT_SLUG,
    TEST_PEPPER,
    create_collection,
    create_tenant,
)
from tests.integration.database import run_sql
from tests.integration.worker import run_worker

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_NAME = "rag_test"


def test_database_url() -> str:
    configured = os.environ.get("RAG_TEST_DATABASE_URL")
    if configured:
        return configured
    application = make_url(Settings().database_url)
    return application.set(database=TEST_DATABASE_NAME).render_as_string(hide_password=False)


TEST_DATABASE_URL = test_database_url()
AWS_TEST_ENVIRONMENT = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if Path(item.path).is_relative_to(Path(__file__).parent):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_database(alembic_config: Config) -> str:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
async def session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_database, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def models() -> ModelProvider:
    return FakeModels()


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator["S3Client"]:
    for name, value in AWS_TEST_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        client = boto3.client("s3", region_name=AWS_TEST_ENVIRONMENT["AWS_DEFAULT_REGION"])
        client.create_bucket(Bucket=PLATFORM_BUCKET)
        yield client


@pytest.fixture
def settings(
    migrated_database: str,
    s3: "S3Client",
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Settings]:
    environment = SMALL_CHUNKS | {
        "RAG_DATABASE_URL": migrated_database,
        "RAG_STORAGE_BACKEND": "s3",
        "RAG_STORAGE_BUCKET": PLATFORM_BUCKET,
        "RAG_STORAGE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "RAG_JOB_RETRY_BASE_SECONDS": "0",
        "RAG_API_KEY_PEPPER": TEST_PEPPER,
        "RAG_PLATFORM_ADMIN_KEY": PLATFORM_ADMIN_KEY,
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def api(
    migrated_database: str,
    settings: Settings,
    models: ModelProvider,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_models] = lambda: models
    create_tenant(migrated_database, TENANT_SLUG)
    try:
        with TestClient(app, follow_redirects=False) as client:
            app.state.rate_limiter = RedisRateLimiter(FakeRedis())
            create_collection(client, "support")
            yield client
    finally:
        run_sql(migrated_database, "TRUNCATE tenants CASCADE")


@pytest.fixture
def drain(api: TestClient, settings: Settings, models: ModelProvider) -> Callable[[], int]:
    def run() -> int:
        return asyncio.run(run_worker(settings, models))

    return run
