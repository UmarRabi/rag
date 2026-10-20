import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from tests.integration.client import AUTHENTICATED, as_tenant, create_tenant, issue_key
from tests.integration.database import run_sql

SEARCH_BODY = {"query": "refund"}


@pytest.fixture
def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {"RAG_RATE_LIMIT_SEARCH": "2", "RAG_RATE_LIMIT_API": "3"}.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def test_responses_carry_rate_limit_headers(api: TestClient) -> None:
    response = api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED)

    assert response.headers["x-ratelimit-limit"] == "60"
    assert response.headers["x-ratelimit-remaining"] == "59"
    assert 1 <= int(response.headers["x-ratelimit-reset"]) <= 60


def test_requests_over_the_limit_get_429(api: TestClient, small_limits: None) -> None:
    statuses = [api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED) for _ in range(3)]

    assert [response.status_code for response in statuses] == [200, 200, 429]
    refused = statuses[-1]
    assert refused.headers["x-ratelimit-remaining"] == "0"
    assert int(refused.headers["retry-after"]) >= 1


def test_search_and_other_calls_have_separate_budgets(api: TestClient, small_limits: None) -> None:
    for _ in range(2):
        api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED)

    assert api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED).status_code == 429
    assert api.get("/v1/collections", headers=AUTHENTICATED).status_code == status.HTTP_200_OK


def test_each_key_has_its_own_budget(
    api: TestClient,
    small_limits: None,
    migrated_database: str,
) -> None:
    create_tenant(migrated_database, "globex")
    for _ in range(3):
        api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED)

    assert api.post("/v1/search", json=SEARCH_BODY, headers=as_tenant("globex")).status_code == 200


def test_tenant_settings_override_the_defaults(api: TestClient, migrated_database: str) -> None:
    uncached = issue_key(migrated_database, ["search"])
    run_sql(
        migrated_database,
        """UPDATE tenants SET settings = '{"rate_limits": {"search": 1}}' WHERE slug = 'acme'""",
    )

    responses = [api.post("/v1/search", json=SEARCH_BODY, headers=uncached) for _ in range(2)]

    assert [response.status_code for response in responses] == [200, 429]
