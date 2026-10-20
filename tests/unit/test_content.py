import hashlib
import io

import pytest
from uuid_utils.compat import uuid7

from app.core.errors import PayloadTooLargeError
from app.ingestion.content import fingerprint, object_key, object_name
from app.storage.base import InvalidStorageUriError, StorageLocation


def test_fingerprint_hashes_the_whole_stream_and_rewinds() -> None:
    stream = io.BytesIO(b"x" * 3_000_000)

    result = fingerprint(stream, limit_bytes=5_000_000)

    assert result.content_hash == hashlib.sha256(b"x" * 3_000_000).hexdigest()
    assert result.size_bytes == 3_000_000
    assert stream.tell() == 0


def test_fingerprint_stops_at_the_size_limit() -> None:
    with pytest.raises(PayloadTooLargeError):
        fingerprint(io.BytesIO(b"x" * 2048), limit_bytes=1024)


@pytest.mark.parametrize(
    ("filename", "mime_type", "name"),
    [
        ("Quarterly Report (final).pdf", "application/pdf", "Quarterly-Report-final-.pdf"),
        ("../../etc/passwd", "text/plain", "passwd"),
        (None, "text/plain", "content.txt"),
        ("...", "application/pdf", "content.pdf"),
    ],
)
def test_object_names_are_safe(filename: str | None, mime_type: str, name: str) -> None:
    assert object_name(filename, mime_type) == name


def test_object_keys_are_scoped_by_tenant_collection_and_document() -> None:
    tenant, collection, document = uuid7(), uuid7(), uuid7()

    key = object_key(
        tenant_id=tenant,
        collection_id=collection,
        document_id=document,
        content_hash="abcdef0123456789ffff",
        name="a.pdf",
    )

    assert key == f"{tenant}/{collection}/{document}/abcdef0123456789/a.pdf"


def test_storage_locations_round_trip_through_uris() -> None:
    location = StorageLocation.parse("s3://bucket/path/to/file.pdf")

    assert (location.bucket, location.key, location.uri) == (
        "bucket",
        "path/to/file.pdf",
        "s3://bucket/path/to/file.pdf",
    )


@pytest.mark.parametrize("uri", ["https://bucket/key", "s3://bucket", "s3:///key"])
def test_invalid_storage_uris_are_rejected(uri: str) -> None:
    with pytest.raises(InvalidStorageUriError):
        StorageLocation.parse(uri)
