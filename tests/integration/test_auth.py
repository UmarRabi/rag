from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.auth.keys import ApiKeyToken
from tests.integration.client import AUTHENTICATED, bearer, issue_key
from tests.integration.database import run_sql

SEARCH_BODY = {"query": "refund"}


def test_search_keys_can_search_and_read_but_not_write(
    api: TestClient,
    migrated_database: str,
) -> None:
    headers = issue_key(migrated_database, ["search"])

    assert (
        api.post("/v1/search", json=SEARCH_BODY, headers=headers).status_code == status.HTTP_200_OK
    )
    assert api.get("/v1/collections", headers=headers).status_code == status.HTTP_200_OK

    denied = api.post("/v1/ingest", json={"collection": "support", "text": "Hi"}, headers=headers)
    assert denied.status_code == status.HTTP_403_FORBIDDEN
    assert "'ingest' scope" in denied.json()["detail"]


def test_ingest_keys_cannot_manage_storage_or_keys(api: TestClient, migrated_database: str) -> None:
    headers = issue_key(migrated_database, ["ingest"])

    ingested = api.post("/v1/ingest", json={"collection": "support", "text": "Hi"}, headers=headers)
    assert ingested.status_code == status.HTTP_202_ACCEPTED
    for path in ("/v1/storage-connections", "/v1/api-keys"):
        assert api.get(path, headers=headers).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer not-a-key",
        "Basic dXNlcjpwYXNz",
        f"Bearer {ApiKeyToken.issue().value}",
    ],
)
def test_missing_or_invalid_keys_are_unauthorized(
    api: TestClient, authorization: str | None
) -> None:
    headers = {"Authorization": authorization} if authorization else {}

    response = api.post("/v1/search", json=SEARCH_BODY, headers=headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_correct_prefix_with_the_wrong_secret_is_unauthorized(api: TestClient) -> None:
    genuine = ApiKeyToken.parse(AUTHENTICATED["Authorization"].removeprefix("Bearer "))
    assert genuine is not None
    forged = ApiKeyToken(genuine.prefix, ApiKeyToken.issue().secret)

    assert api.post("/v1/search", json=SEARCH_BODY, headers=bearer(forged.value)).status_code == 401


def test_expired_keys_are_unauthorized(api: TestClient, migrated_database: str) -> None:
    headers = issue_key(
        migrated_database, ["search"], expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )

    assert api.post("/v1/search", json=SEARCH_BODY, headers=headers).status_code == 401


def test_keys_of_suspended_tenants_are_unauthorized(
    api: TestClient, migrated_database: str
) -> None:
    uncached = issue_key(migrated_database, ["search"])
    run_sql(migrated_database, "UPDATE tenants SET status = 'suspended' WHERE slug = 'acme'")

    assert api.post("/v1/search", json=SEARCH_BODY, headers=uncached).status_code == 401


def test_created_keys_work_and_are_shown_only_once(api: TestClient) -> None:
    created = api.post(
        "/v1/api-keys",
        json={"name": "Widget", "scopes": ["search"]},
        headers=AUTHENTICATED,
    )

    assert created.status_code == status.HTTP_201_CREATED
    body = created.json()
    assert body["token"].startswith(f"rag_{body['prefix']}_")
    assert (
        api.post("/v1/search", json=SEARCH_BODY, headers=bearer(body["token"])).status_code == 200
    )

    listed = api.get("/v1/api-keys", headers=AUTHENTICATED).json()
    assert {key["name"] for key in listed} == {"admin key", "Widget"}
    assert all("token" not in key and "key_hash" not in key for key in listed)


def test_revoked_keys_stop_working_immediately(api: TestClient) -> None:
    created = api.post(
        "/v1/api-keys", json={"name": "Temp", "scopes": ["search"]}, headers=AUTHENTICATED
    ).json()
    headers = bearer(created["token"])
    assert api.post("/v1/search", json=SEARCH_BODY, headers=headers).status_code == 200

    revoked = api.delete(f"/v1/api-keys/{created['id']}", headers=AUTHENTICATED)

    assert revoked.status_code == status.HTTP_204_NO_CONTENT
    assert api.post("/v1/search", json=SEARCH_BODY, headers=headers).status_code == 401


def test_usage_is_recorded_on_the_key(api: TestClient, migrated_database: str) -> None:
    api.post("/v1/search", json=SEARCH_BODY, headers=AUTHENTICATED)

    (row,) = run_sql(
        migrated_database, "SELECT last_used_at FROM api_keys WHERE name = 'admin key'"
    )
    assert row.last_used_at is not None


@pytest.mark.parametrize("scopes", [[], ["superuser"]])
def test_keys_need_known_scopes(api: TestClient, scopes: list[str]) -> None:
    response = api.post(
        "/v1/api-keys", json={"name": "Bad", "scopes": scopes}, headers=AUTHENTICATED
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
