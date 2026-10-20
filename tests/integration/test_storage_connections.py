from typing import TYPE_CHECKING, Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from httpx2 import Response

from app.storage.base import StorageLocation
from tests.integration.client import (
    AUTHENTICATED,
    as_tenant,
    create_collection,
    create_tenant,
    upload,
)
from tests.integration.database import run_sql

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

CLIENT_BUCKET = "acme-own-bucket"
SECRET = "client-secret-value"
ACCESS_KEY = {
    "name": "Acme bucket",
    "provider": "s3",
    "bucket": CLIENT_BUCKET,
    "region": "us-east-1",
    "prefix": "rag",
    "auth_type": "access_key",
    "access_key_id": "AKIACLIENT",
    "secret_access_key": SECRET,
}
ASSUME_ROLE = {
    "name": "Acme role",
    "provider": "s3",
    "bucket": CLIENT_BUCKET,
    "region": "us-east-1",
    "auth_type": "assume_role",
    "role_arn": "arn:aws:iam::123456789012:role/interra-rag",
    "external_id": "acme-external-id",
}


@pytest.fixture
def client_bucket(s3: "S3Client") -> str:
    s3.create_bucket(Bucket=CLIENT_BUCKET)
    return CLIENT_BUCKET


def connect(api: TestClient, tenant: str = "acme", **fields: Any) -> Response:
    return api.post("/v1/storage-connections", json=ACCESS_KEY | fields, headers=as_tenant(tenant))


def stored_location(database: str, document_id: str) -> StorageLocation:
    (row,) = run_sql(database, "SELECT storage_uri FROM documents WHERE id = :id", id=document_id)
    return StorageLocation.parse(row.storage_uri)


def test_access_key_connection_is_verified_and_never_echoes_secrets(
    api: TestClient,
    client_bucket: str,
    migrated_database: str,
) -> None:
    response = connect(api)

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["status"] == "verified"
    assert body["verified_at"] is not None
    assert "secret_access_key" not in body
    assert "access_key_id" not in body
    (row,) = run_sql(migrated_database, "SELECT credentials_encrypted FROM storage_connections")
    assert SECRET.encode() not in bytes(row.credentials_encrypted)


def test_assume_role_connection_is_verified(api: TestClient, client_bucket: str) -> None:
    body = api.post("/v1/storage-connections", json=ASSUME_ROLE, headers=AUTHENTICATED).json()

    assert body["status"] == "verified"
    assert body["external_id"] == "acme-external-id"


def test_unreachable_bucket_is_marked_failed(api: TestClient) -> None:
    body = connect(api, bucket="missing-bucket").json()

    assert body["status"] == "failed"
    assert body["last_error"]


def test_failed_connection_can_be_verified_again(
    api: TestClient,
    s3: "S3Client",
) -> None:
    connection = connect(api).json()
    s3.create_bucket(Bucket=CLIENT_BUCKET)

    response = api.post(f"/v1/storage-connections/{connection['id']}/verify", headers=AUTHENTICATED)

    assert response.json()["status"] == "verified"


def test_collection_bucket_receives_uploads(
    api: TestClient,
    client_bucket: str,
    s3: "S3Client",
    migrated_database: str,
) -> None:
    connection = connect(api).json()
    api.patch(
        "/v1/collections/support",
        json={"storage_connection_id": connection["id"]},
        headers=AUTHENTICATED,
    )

    document_id = upload(api, b"Client owned file.", "owned.txt", "text/plain").json()[
        "document_id"
    ]

    location = stored_location(migrated_database, document_id)
    assert location.bucket == client_bucket
    assert location.key.startswith("rag/")
    assert (
        s3.get_object(Bucket=location.bucket, Key=location.key)["Body"].read()
        == b"Client owned file."
    )


def test_tenant_default_bucket_is_used_when_the_collection_has_none(
    api: TestClient,
    client_bucket: str,
    migrated_database: str,
) -> None:
    connect(api, is_default=True)

    document_id = upload(api, b"Default bucket file.", "default.txt", "text/plain").json()[
        "document_id"
    ]

    assert stored_location(migrated_database, document_id).bucket == client_bucket


def test_new_default_replaces_the_previous_default(api: TestClient, client_bucket: str) -> None:
    connect(api, name="First", is_default=True)
    connect(api, name="Second", is_default=True)

    defaults = {
        connection["name"]: connection["is_default"]
        for connection in api.get("/v1/storage-connections", headers=AUTHENTICATED).json()
    }
    assert defaults == {"First": False, "Second": True}


def test_unverified_connection_blocks_uploads(api: TestClient) -> None:
    connection = connect(api, bucket="missing-bucket").json()
    api.patch(
        "/v1/collections/support",
        json={"storage_connection_id": connection["id"]},
        headers=AUTHENTICATED,
    )

    response = upload(api, b"Nowhere to go.", "lost.txt", "text/plain")

    assert response.status_code == status.HTTP_409_CONFLICT


def test_connection_in_use_cannot_be_deleted(api: TestClient, client_bucket: str) -> None:
    connection = connect(api).json()
    create_collection(api, "owned", storage_connection_id=connection["id"])

    response = api.delete(f"/v1/storage-connections/{connection['id']}", headers=AUTHENTICATED)

    assert response.status_code == status.HTTP_409_CONFLICT


def test_unused_connection_can_be_deleted(api: TestClient, client_bucket: str) -> None:
    connection = connect(api).json()

    response = api.delete(f"/v1/storage-connections/{connection['id']}", headers=AUTHENTICATED)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert api.get("/v1/storage-connections", headers=AUTHENTICATED).json() == []


def test_connections_of_other_tenants_cannot_be_assigned(
    api: TestClient,
    client_bucket: str,
    migrated_database: str,
) -> None:
    create_tenant(migrated_database, "globex")
    foreign = connect(api, tenant="globex").json()

    response = api.patch(
        "/v1/collections/support",
        json={"storage_connection_id": foreign["id"]},
        headers=AUTHENTICATED,
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
    "changes",
    [
        {"secret_access_key": None},
        {"auth_type": "assume_role"},
        {"provider": "dropbox"},
    ],
)
def test_incomplete_connections_are_rejected(api: TestClient, changes: dict[str, Any]) -> None:
    assert connect(api, **changes).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
