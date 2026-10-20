import hashlib
import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO

from app.core.errors import PayloadTooLargeError

READ_BLOCK_BYTES = 1024 * 1024
DEFAULT_OBJECT_NAME = "content"
UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILENAME_LENGTH = 120


@dataclass(frozen=True, slots=True)
class IncomingContent:
    stream: BinaryIO
    declared_mime: str | None = None
    filename: str | None = None

    def head(self, size: int) -> bytes:
        self.stream.seek(0)
        head = self.stream.read(size)
        self.stream.seek(0)
        return head


@dataclass(frozen=True, slots=True)
class Fingerprint:
    content_hash: str
    size_bytes: int


def fingerprint(stream: BinaryIO, limit_bytes: int) -> Fingerprint:
    digest = hashlib.sha256()
    size = 0
    stream.seek(0)
    while block := stream.read(READ_BLOCK_BYTES):
        size += len(block)
        if size > limit_bytes:
            raise PayloadTooLargeError(f"Content exceeds {limit_bytes} bytes")
        digest.update(block)
    stream.seek(0)
    return Fingerprint(digest.hexdigest(), size)


def object_name(filename: str | None, mime_type: str) -> str:
    name = PurePath(filename).name if filename else ""
    safe = UNSAFE_FILENAME_CHARACTERS.sub("-", name).strip("-.")[-MAX_FILENAME_LENGTH:]
    if safe:
        return safe
    return DEFAULT_OBJECT_NAME + (mimetypes.guess_extension(mime_type) or "")


def object_key(
    *,
    tenant_id: uuid.UUID,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    content_hash: str,
    name: str,
) -> str:
    return f"{tenant_id}/{collection_id}/{document_id}/{content_hash[:16]}/{name}"
