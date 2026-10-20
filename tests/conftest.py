import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import create_app

TEST_ENVIRONMENT = {"RAG_PRELOAD_MODELS": "false"}


def pytest_configure(config: pytest.Config) -> None:
    os.environ.update(TEST_ENVIRONMENT)
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
