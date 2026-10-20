from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from tests.integration.client import AUTHENTICATED, PLATFORM_ADMIN, bearer

SEARCH_BODY = {"query": "refund"}


def create(api: TestClient, slug: str = "globex", **fields: Any) -> dict[str, Any]:
    response = api.post(
        "/admin/tenants",
        json={"name": slug.title(), "slug": slug} | fields,
        headers=PLATFORM_ADMIN,
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    created: dict[str, Any] = response.json()
    return created


@pytest.mark.parametrize("headers", [{}, bearer("wrong-key"), AUTHENTICATED])
def test_admin_api_needs_the_platform_key(api: TestClient, headers: dict[str, str]) -> None:
    assert api.get("/admin/tenants", headers=headers).status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_api_is_disabled_without_a_platform_key(
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_PLATFORM_ADMIN_KEY", "")
    get_settings.cache_clear()

    response = api.get("/admin/tenants", headers=PLATFORM_ADMIN)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_new_tenants_get_a_working_admin_key(api: TestClient) -> None:
    created = create(api, settings={"rate_limits": {"search": 120}})
    tenant, key = created["tenant"], created["api_key"]

    assert tenant["slug"] == "globex"
    assert tenant["settings"] == {"rate_limits": {"search": 120}}
    assert key["scopes"] == ["admin"]
    headers = bearer(key["token"])
    assert api.get("/v1/api-keys", headers=headers).status_code == status.HTTP_200_OK


def test_duplicate_tenant_slugs_conflict(api: TestClient) -> None:
    response = api.post(
        "/admin/tenants", json={"name": "Acme", "slug": "acme"}, headers=PLATFORM_ADMIN
    )

    assert response.status_code == status.HTTP_409_CONFLICT


def test_tenants_are_listed(api: TestClient) -> None:
    create(api)

    slugs = [tenant["slug"] for tenant in api.get("/admin/tenants", headers=PLATFORM_ADMIN).json()]

    assert slugs == ["acme", "globex"]


def test_suspending_a_tenant_blocks_its_keys_until_reactivated(api: TestClient) -> None:
    assert api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED).status_code == 200

    api.patch("/admin/tenants/acme", json={"status": "suspended"}, headers=PLATFORM_ADMIN)
    assert api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED).status_code == 401

    api.patch("/admin/tenants/acme", json={"status": "active"}, headers=PLATFORM_ADMIN)
    assert api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED).status_code == 200


def test_rate_limit_changes_apply_to_the_next_request(api: TestClient) -> None:
    api.patch(
        "/admin/tenants/acme",
        json={"settings": {"rate_limits": {"search": 1}}},
        headers=PLATFORM_ADMIN,
    )

    responses = [api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED) for _ in range(2)]

    assert [response.status_code for response in responses] == [200, 429]


def test_platform_admin_can_issue_recovery_keys(api: TestClient) -> None:
    response = api.post(
        "/admin/tenants/acme/api-keys",
        json={"name": "Recovery", "scopes": ["admin"]},
        headers=PLATFORM_ADMIN,
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert api.get("/v1/api-keys", headers=bearer(response.json()["token"])).status_code == 200


def test_unknown_tenants_are_not_found(api: TestClient) -> None:
    assert api.get("/admin/tenants/nobody", headers=PLATFORM_ADMIN).status_code == 404
