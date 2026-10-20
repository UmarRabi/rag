import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Response
from uuid_utils.compat import uuid7

from app.auth.keys import PREFIX_LENGTH, SECRET_LENGTH, ApiKeyToken, KeyHasher
from tests.integration.database import run_sql

TENANT_SLUG = "acme"
SMALL_CHUNKS = {"RAG_CHUNK_MAX_TOKENS": "12", "RAG_CHUNK_OVERLAP_TOKENS": "3"}
PLATFORM_BUCKET = "rag-platform-test"
TEST_PEPPER = "test-pepper"
PLATFORM_ADMIN_KEY = "platform-admin-test-key"


def stable_token(seed: str) -> ApiKeyToken:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return ApiKeyToken(
        digest[:PREFIX_LENGTH], (digest * 2)[PREFIX_LENGTH : PREFIX_LENGTH + SECRET_LENGTH]
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def as_tenant(slug: str) -> dict[str, str]:
    return bearer(stable_token(slug).value)


AUTHENTICATED = as_tenant(TENANT_SLUG)
PLATFORM_ADMIN = bearer(PLATFORM_ADMIN_KEY)


def insert_key(
    database: str,
    slug: str,
    token: ApiKeyToken,
    scopes: Sequence[str],
    expires_at: datetime | None = None,
) -> str:
    run_sql(
        database,
        "INSERT INTO api_keys (id, tenant_id, name, prefix, key_hash, scopes, expires_at) "
        "SELECT :id, id, :name, :prefix, :hash, :scopes, :expires_at "
        "FROM tenants WHERE slug = :slug",
        id=uuid7(),
        name=f"{','.join(scopes)} key",
        prefix=token.prefix,
        hash=KeyHasher(TEST_PEPPER).digest(token.secret),
        scopes=list(scopes),
        expires_at=expires_at,
        slug=slug,
    )
    return token.value


def create_tenant(database: str, slug: str) -> str:
    run_sql(
        database,
        "INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)",
        id=uuid7(),
        name=slug.title(),
        slug=slug,
    )
    return insert_key(database, slug, stable_token(slug), ["admin"])


def issue_key(
    database: str,
    scopes: Sequence[str],
    slug: str = TENANT_SLUG,
    expires_at: datetime | None = None,
) -> dict[str, str]:
    return bearer(insert_key(database, slug, ApiKeyToken.issue(), scopes, expires_at))


def create_collection(
    client: TestClient,
    slug: str,
    tenant: str = TENANT_SLUG,
    **fields: Any,
) -> Response:
    return client.post(
        "/v1/collections",
        json={"name": slug.title(), "slug": slug} | fields,
        headers=as_tenant(tenant),
    )


def ingest(client: TestClient, tenant: str = TENANT_SLUG, **fields: Any) -> Response:
    body = {"collection": "support", "text": "How do I reset my password?"} | fields
    return client.post("/v1/ingest", json=body, headers=as_tenant(tenant))


def upload(
    client: TestClient,
    data: bytes,
    filename: str,
    mime_type: str = "application/octet-stream",
    tenant: str = TENANT_SLUG,
    **fields: str,
) -> Response:
    return client.post(
        "/v1/ingest",
        files={"file": (filename, data, mime_type)},
        data={"collection": "support"} | fields,
        headers=as_tenant(tenant),
    )


def document(client: TestClient, document_id: str, tenant: str = TENANT_SLUG) -> dict[str, Any]:
    response = client.get(f"/v1/documents/{document_id}", headers=as_tenant(tenant))
    body: dict[str, Any] = response.json()
    return body


def search(client: TestClient, query: str, tenant: str = TENANT_SLUG, **fields: Any) -> Response:
    return client.post("/v1/search", json={"query": query} | fields, headers=as_tenant(tenant))
