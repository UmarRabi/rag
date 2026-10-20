from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest
from botocore.exceptions import ClientError
from fastapi import status
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.storage.base import StorageLocation
from tests.documents import (
    DOCX_MIME,
    PPTX_MIME,
    XLSX_MIME,
    docx_document,
    html_document,
    pdf_document,
    pptx_document,
    xlsx_document,
)
from tests.fakes import FakeModels
from tests.integration.client import AUTHENTICATED, PLATFORM_BUCKET, document, upload
from tests.integration.database import run_sql

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def chunks(database: str, document_id: str) -> list[tuple[str, str, int | None]]:
    rows = run_sql(
        database,
        "SELECT content, modality, page FROM chunks WHERE document_id = :id ORDER BY position",
        id=document_id,
    )
    return [(row.content, row.modality, row.page) for row in rows]


def stored_location(document_id: str, database: str) -> StorageLocation:
    (row,) = run_sql(database, "SELECT storage_uri FROM documents WHERE id = :id", id=document_id)
    return StorageLocation.parse(row.storage_uri)


def object_exists(s3: "S3Client", location: StorageLocation) -> bool:
    try:
        s3.head_object(Bucket=location.bucket, Key=location.key)
    except ClientError:
        return False
    return True


ZIP_ARCHIVE = bytes([0x50, 0x4B, 0x05, 0x06]) + bytes(18)
MARKDOWN = "\n\n".join(["# Shipping", "We ship daily."]).encode()


@pytest.mark.parametrize(
    ("data", "filename", "mime_type", "media_type", "expected"),
    [
        pytest.param(
            pdf_document("Warranty covers two years."),
            "warranty.pdf",
            "application/pdf",
            "pdf",
            "Warranty covers two years.",
            id="pdf",
        ),
        pytest.param(
            docx_document(),
            "returns.docx",
            DOCX_MIME,
            "docx",
            "Items can be returned within 30 days.",
            id="docx",
        ),
        pytest.param(
            pptx_document(),
            "onboarding.pptx",
            PPTX_MIME,
            "pptx",
            "Mention the gym discount",
            id="pptx",
        ),
        pytest.param(
            xlsx_document(),
            "prices.xlsx",
            XLSX_MIME,
            "xlsx",
            "Product: Router X | Price: 120",
            id="xlsx",
        ),
        pytest.param(
            html_document(), "help.html", "text/html", "html", "Hold the reset button", id="html"
        ),
        pytest.param(
            MARKDOWN, "shipping.md", "text/markdown", "text", "We ship daily.", id="markdown"
        ),
    ],
)
def test_uploaded_files_are_extracted_and_indexed(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
    data: bytes,
    filename: str,
    mime_type: str,
    media_type: str,
    expected: str,
) -> None:
    response = upload(api, data, filename, mime_type)
    assert response.status_code == status.HTTP_202_ACCEPTED, response.text
    body = response.json()
    assert (body["media_type"], body["status"]) == (media_type, "queued")

    drain()

    ready = document(api, body["document_id"])
    assert ready["status"] == "ready", ready["error"]
    assert ready["title"] == filename
    combined = "\n".join(
        content for content, _, _ in chunks(migrated_database, body["document_id"])
    )
    assert expected in combined


def test_type_is_detected_from_content_not_the_declared_type(api: TestClient) -> None:
    body = upload(api, pdf_document("Hello"), "notes.txt", "text/plain").json()

    assert body["media_type"] == "pdf"


def test_pages_and_slides_keep_their_numbers(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    body = upload(
        api, pdf_document("First page text here.", "Second page text here."), "a.pdf"
    ).json()
    drain()

    assert [page for _, _, page in chunks(migrated_database, body["document_id"])] == [1, 2]


def test_scanned_pdf_pages_are_read_with_ocr(
    api: TestClient,
    drain: Callable[[], int],
    models: FakeModels,
    migrated_database: str,
) -> None:
    body = upload(api, pdf_document("Typed page with plenty of text.", ""), "scan.pdf").json()
    drain()

    assert models.ocr_engine.calls == 1
    assert chunks(migrated_database, body["document_id"])[-1] == (
        "Scanned invoice\nTotal due 120 USD",
        "ocr",
        2,
    )


def test_unsupported_media_is_rejected_before_queueing(
    api: TestClient, migrated_database: str
) -> None:
    response = upload(api, ZIP_ARCHIVE, "archive.zip", "application/zip")

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert run_sql(migrated_database, "SELECT id FROM documents") == []


def test_unknown_binary_is_rejected(api: TestClient) -> None:
    response = upload(api, bytes(range(256)) * 4, "blob.bin")

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


def test_files_over_the_limit_are_rejected(
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MAX_DOCUMENT_BYTES", "1024")
    get_settings.cache_clear()

    response = upload(api, b"a" * 2048, "big.txt", "text/plain")

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE


def test_upload_without_a_file_is_rejected(api: TestClient) -> None:
    response = api.post(
        "/v1/ingest",
        data={"collection": "support"},
        files={"other": ("a.txt", b"x", "text/plain")},
        headers=AUTHENTICATED,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_metadata_is_accepted_as_json_text(api: TestClient) -> None:
    body = upload(
        api, b"Router manual.", "manual.txt", "text/plain", metadata='{"product": "router-x"}'
    ).json()

    assert document(api, body["document_id"])["metadata"] == {"product": "router-x"}


def test_originals_are_stored_in_the_platform_bucket(
    api: TestClient,
    s3: "S3Client",
    migrated_database: str,
) -> None:
    body = upload(api, b"Stored text.", "stored.txt", "text/plain").json()

    location = stored_location(body["document_id"], migrated_database)
    assert location.bucket == PLATFORM_BUCKET
    assert location.key.endswith("/stored.txt")
    assert s3.get_object(Bucket=location.bucket, Key=location.key)["Body"].read() == b"Stored text."


def test_download_redirects_to_a_presigned_url(api: TestClient, migrated_database: str) -> None:
    body = upload(api, b"Download me.", "download.txt", "text/plain").json()

    response = api.get(f"/v1/documents/{body['document_id']}/file", headers=AUTHENTICATED)

    location = stored_location(body["document_id"], migrated_database)
    assert response.status_code == status.HTTP_307_TEMPORARY_REDIRECT
    assert location.key in response.headers["location"]
    assert "Signature=" in response.headers["location"]


def test_delete_removes_the_document_its_chunks_and_its_file(
    api: TestClient,
    drain: Callable[[], int],
    s3: "S3Client",
    migrated_database: str,
) -> None:
    body = upload(api, b"Delete me soon.", "delete.txt", "text/plain").json()
    drain()
    location = stored_location(body["document_id"], migrated_database)

    response = api.delete(f"/v1/documents/{body['document_id']}", headers=AUTHENTICATED)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert api.get(f"/v1/documents/{body['document_id']}", headers=AUTHENTICATED).status_code == 404
    assert chunks(migrated_database, body["document_id"]) == []
    assert not object_exists(s3, location)


def test_replacing_by_external_id_removes_the_old_file(
    api: TestClient,
    s3: "S3Client",
    migrated_database: str,
) -> None:
    first = upload(api, b"Version one.", "policy.txt", "text/plain", external_id="policy").json()
    old = stored_location(first["document_id"], migrated_database)
    upload(api, b"Version two.", "policy.txt", "text/plain", external_id="policy")

    new = stored_location(first["document_id"], migrated_database)
    assert new != old
    assert not object_exists(s3, old)
    assert object_exists(s3, new)
