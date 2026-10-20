import io
from pathlib import Path

import pytest

from app.storage.base import StorageLocation
from app.storage.local import LocalFileStorage, UnsafeStorageKeyError


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path)


async def test_stores_reads_and_deletes_files(storage: LocalFileStorage, tmp_path: Path) -> None:
    location = await storage.put(
        "tenant/doc/report.pdf", io.BytesIO(b"%PDF data"), "application/pdf"
    )

    assert location.uri == "local://platform/tenant/doc/report.pdf"
    assert (tmp_path / "platform" / "tenant" / "doc" / "report.pdf").read_bytes() == b"%PDF data"
    assert await storage.get(StorageLocation.parse(location.uri)) == b"%PDF data"

    await storage.delete(location)
    await storage.delete(location)
    assert not (tmp_path / "platform" / "tenant" / "doc" / "report.pdf").exists()


async def test_local_files_have_no_presigned_url(storage: LocalFileStorage) -> None:
    location = await storage.put("a.txt", io.BytesIO(b"a"), "text/plain")

    assert await storage.presigned_url(location, 60) is None


async def test_keys_cannot_escape_the_storage_root(storage: LocalFileStorage) -> None:
    with pytest.raises(UnsafeStorageKeyError):
        await storage.get(StorageLocation("platform", "../../secrets.txt", "local"))
