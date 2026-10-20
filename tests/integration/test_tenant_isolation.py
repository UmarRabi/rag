from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from tests.integration.client import (
    AUTHENTICATED,
    as_tenant,
    create_collection,
    create_tenant,
    ingest,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

INTRUDER = "globex"
SECRET_TEXT = "Acme confidential pricing for 2027."


@pytest.fixture
def acme(
    api: TestClient,
    drain: Callable[[], int],
    s3: "S3Client",
    migrated_database: str,
) -> dict[str, str]:
    s3.create_bucket(Bucket="acme-private")
    connection = api.post(
        "/v1/storage-connections",
        json={
            "name": "Private",
            "provider": "s3",
            "bucket": "acme-private",
            "region": "us-east-1",
            "auth_type": "access_key",
            "access_key_id": "AKIAACME",
            "secret_access_key": "acme-secret",
        },
        headers=AUTHENTICATED,
    ).json()
    key = api.post(
        "/v1/api-keys", json={"name": "Widget", "scopes": ["search"]}, headers=AUTHENTICATED
    ).json()
    document_id = ingest(api, text=SECRET_TEXT).json()["document_id"]
    drain()
    create_tenant(migrated_database, INTRUDER)
    create_collection(api, "support", tenant=INTRUDER)
    return {"document": document_id, "connection": connection["id"], "key": key["id"]}


def requests_against(acme: dict[str, str]) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", f"/v1/documents/{acme['document']}", None),
        ("GET", f"/v1/documents/{acme['document']}/file", None),
        ("DELETE", f"/v1/documents/{acme['document']}", None),
        ("POST", f"/v1/storage-connections/{acme['connection']}/verify", None),
        ("DELETE", f"/v1/storage-connections/{acme['connection']}", None),
        ("DELETE", f"/v1/api-keys/{acme['key']}", None),
        ("PATCH", "/v1/collections/support", {"storage_connection_id": acme["connection"]}),
        (
            "POST",
            "/v1/collections",
            {"name": "Mine", "slug": "mine", "storage_connection_id": acme["connection"]},
        ),
    ]


def test_other_tenants_get_not_found_for_every_resource(
    api: TestClient, acme: dict[str, str]
) -> None:
    for method, path, body in requests_against(acme):
        response = api.request(method, path, json=body, headers=as_tenant(INTRUDER))

        assert response.status_code == status.HTTP_404_NOT_FOUND, f"{method} {path}"


def test_acme_resources_survive_the_attempts(api: TestClient, acme: dict[str, str]) -> None:
    for method, path, body in requests_against(acme):
        api.request(method, path, json=body, headers=as_tenant(INTRUDER))

    assert api.get(f"/v1/documents/{acme['document']}", headers=AUTHENTICATED).status_code == 200
    assert len(api.get("/v1/storage-connections", headers=AUTHENTICATED).json()) == 1
    assert len(api.get("/v1/api-keys", headers=AUTHENTICATED).json()) == 2


def test_listings_only_show_the_callers_own_resources(
    api: TestClient, acme: dict[str, str]
) -> None:
    headers = as_tenant(INTRUDER)

    assert api.get("/v1/storage-connections", headers=headers).json() == []
    assert [key["name"] for key in api.get("/v1/api-keys", headers=headers).json()] == ["admin key"]
    assert [
        collection["slug"] for collection in api.get("/v1/collections", headers=headers).json()
    ] == ["support"]


def test_search_never_returns_another_tenants_chunks(api: TestClient, acme: dict[str, str]) -> None:
    for mode in ("hybrid", "vector", "keyword"):
        response = api.post(
            "/v1/search",
            json={"query": SECRET_TEXT, "mode": mode, "top_k": 50},
            headers=as_tenant(INTRUDER),
        )

        assert response.json()["results"] == [], mode


def test_ingesting_into_another_tenants_collection_is_not_possible(
    api: TestClient,
    acme: dict[str, str],
) -> None:
    create_collection(api, "pricing")

    response = ingest(api, tenant=INTRUDER, collection="pricing", text="Injected")

    assert response.status_code == status.HTTP_404_NOT_FOUND
