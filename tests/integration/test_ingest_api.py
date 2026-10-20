from collections.abc import Callable

from fastapi import status
from fastapi.testclient import TestClient

from app.auth.keys import ApiKeyToken
from tests.fakes import FailingEmbedder, FakeModels, HashingEmbedder
from tests.integration.client import (
    AUTHENTICATED,
    SMALL_CHUNKS,
    bearer,
    document,
    ingest,
    issue_key,
)
from tests.integration.database import run_sql

MAX_ATTEMPTS = 5


def chunk_contents(database: str, document_id: str) -> list[str]:
    rows = run_sql(
        database,
        "SELECT content FROM chunks WHERE document_id = :id ORDER BY position",
        id=document_id,
    )
    return [row.content for row in rows]


def job_states(database: str, document_id: str) -> list[tuple[str, int]]:
    rows = run_sql(
        database,
        "SELECT status, attempts FROM jobs WHERE document_id = :id ORDER BY created_at",
        id=document_id,
    )
    return [(row.status, row.attempts) for row in rows]


def test_ingest_queues_the_document(api: TestClient, migrated_database: str) -> None:
    response = ingest(api)

    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()
    assert (body["status"], body["chunk_count"], body["duplicate"]) == ("queued", 0, False)
    assert job_states(migrated_database, body["document_id"]) == [("pending", 0)]


def test_worker_makes_ingested_text_searchable(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    document_id = ingest(api, title="Password help", metadata={"audience": "public"}).json()[
        "document_id"
    ]

    assert drain() == 1

    ready = document(api, document_id)
    assert (ready["status"], ready["chunk_count"], ready["language"]) == ("ready", 1, "en")
    (row,) = run_sql(
        migrated_database,
        "SELECT text_search_config::text AS config, metadata, embedding_model "
        "FROM chunks WHERE document_id = :id",
        id=document_id,
    )
    assert (row.config, row.metadata, row.embedding_model) == (
        "english",
        {"audience": "public"},
        "test/hashing-embedder",
    )
    assert job_states(migrated_database, document_id) == [("succeeded", 1)]


def test_long_text_is_split_into_chunks(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    text = " ".join(f"Sentence number {index} about refunds." for index in range(20))
    document_id = ingest(api, text=text).json()["document_id"]
    drain()

    contents = chunk_contents(migrated_database, document_id)
    assert document(api, document_id)["chunk_count"] == len(contents) > 1
    assert all(
        len(content.split()) <= int(SMALL_CHUNKS["RAG_CHUNK_MAX_TOKENS"]) for content in contents
    )


def test_identical_content_returns_the_existing_document(api: TestClient) -> None:
    first = ingest(api).json()
    second = ingest(api).json()

    assert second["document_id"] == first["document_id"]
    assert second["duplicate"] is True


def test_external_id_replaces_previous_content(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    first = ingest(api, external_id="kb-42", text="Old refund policy.").json()
    drain()
    second = ingest(api, external_id="kb-42", text="New refund policy.").json()
    drain()

    assert second["document_id"] == first["document_id"]
    assert second["duplicate"] is False
    assert chunk_contents(migrated_database, second["document_id"]) == ["New refund policy."]


def test_transient_failures_retry_until_attempts_run_out(
    api: TestClient,
    drain: Callable[[], int],
    models: FakeModels,
    migrated_database: str,
) -> None:
    models.text_embedder = FailingEmbedder()
    document_id = ingest(api).json()["document_id"]

    assert drain() == MAX_ATTEMPTS

    failed = document(api, document_id)
    assert (failed["status"], failed["error"]) == ("failed", "Embedding model unavailable")
    assert job_states(migrated_database, document_id) == [("failed", MAX_ATTEMPTS)]


def test_unreadable_content_fails_without_retrying(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    document_id = ingest(api, text="\u200b\u200b").json()["document_id"]

    assert drain() == 1

    assert document(api, document_id)["status"] == "failed"
    assert job_states(migrated_database, document_id) == [("failed", 1)]


def test_unknown_collection_is_not_found(api: TestClient) -> None:
    assert ingest(api, collection="billing").status_code == status.HTTP_404_NOT_FOUND


def test_unknown_api_key_is_unauthorized(api: TestClient) -> None:
    response = api.post(
        "/v1/ingest",
        json={"collection": "support", "text": "Hello"},
        headers=bearer(ApiKeyToken.issue().value),
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_missing_api_key_is_unauthorized(api: TestClient) -> None:
    response = api.post("/v1/ingest", json={"collection": "support", "text": "Hello"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_invalid_json_body_is_rejected(api: TestClient) -> None:
    response = api.post("/v1/ingest", json={"collection": "support"}, headers=AUTHENTICATED)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_other_content_types_are_rejected(api: TestClient) -> None:
    response = api.post(
        "/v1/ingest",
        content=b"plain body",
        headers=AUTHENTICATED | {"Content-Type": "text/plain"},
    )

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


def test_duplicate_collection_slug_conflicts(api: TestClient) -> None:
    response = api.post(
        "/v1/collections",
        json={"name": "Support again", "slug": "support"},
        headers=AUTHENTICATED,
    )

    assert response.status_code == status.HTTP_409_CONFLICT


def test_collections_are_listed_for_the_tenant(api: TestClient) -> None:
    response = api.get("/v1/collections", headers=AUTHENTICATED)

    assert [collection["slug"] for collection in response.json()] == ["support"]


def test_uploading_a_failed_document_again_retries_it(
    api: TestClient,
    drain: Callable[[], int],
    models: FakeModels,
) -> None:
    models.text_embedder = FailingEmbedder()
    first = ingest(api).json()
    drain()
    assert document(api, first["document_id"])["status"] == "failed"

    models.text_embedder = HashingEmbedder()
    again = ingest(api).json()

    assert (again["document_id"], again["status"], again["duplicate"]) == (
        first["document_id"],
        "queued",
        True,
    )
    drain()
    assert document(api, first["document_id"])["status"] == "ready"


def test_reprocessing_rebuilds_a_documents_chunks(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    document_id = ingest(api, text="Refunds take five days.").json()["document_id"]
    drain()
    run_sql(migrated_database, "DELETE FROM chunks WHERE document_id = :id", id=document_id)

    response = api.post(f"/v1/documents/{document_id}/reprocess", headers=AUTHENTICATED)

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["status"] == "queued"
    drain()
    assert chunk_contents(migrated_database, document_id) == ["Refunds take five days."]
    assert job_states(migrated_database, document_id)[-1] == ("succeeded", 1)


def test_reprocessing_needs_the_ingest_scope(api: TestClient, migrated_database: str) -> None:
    document_id = ingest(api).json()["document_id"]

    response = api.post(
        f"/v1/documents/{document_id}/reprocess",
        headers=issue_key(migrated_database, ["search"]),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
