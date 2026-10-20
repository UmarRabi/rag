from dataclasses import dataclass
from pathlib import PurePath

import filetype

from app.core.errors import UnsupportedMediaTypeError
from app.domain.enums import MediaType

SNIFF_BYTES = 8192
UTF8_MAX_CONTINUATION = 3
ZIP_MIME = "application/zip"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HTML_MARKERS = (b"<!doctype html", b"<html")

MIME_MEDIA_TYPES = {
    "text/plain": MediaType.TEXT,
    "text/markdown": MediaType.TEXT,
    "text/csv": MediaType.TEXT,
    "application/json": MediaType.TEXT,
    "text/html": MediaType.HTML,
    "application/xhtml+xml": MediaType.HTML,
    "application/pdf": MediaType.PDF,
    DOCX_MIME: MediaType.DOCX,
    PPTX_MIME: MediaType.PPTX,
    XLSX_MIME: MediaType.XLSX,
    "image/png": MediaType.IMAGE,
    "image/jpeg": MediaType.IMAGE,
    "image/webp": MediaType.IMAGE,
    "image/gif": MediaType.IMAGE,
    "image/tiff": MediaType.IMAGE,
    "image/bmp": MediaType.IMAGE,
    "audio/mpeg": MediaType.AUDIO,
    "audio/x-wav": MediaType.AUDIO,
    "audio/wav": MediaType.AUDIO,
    "audio/mp4": MediaType.AUDIO,
    "audio/x-m4a": MediaType.AUDIO,
    "audio/m4a": MediaType.AUDIO,
    "audio/ogg": MediaType.AUDIO,
    "audio/x-flac": MediaType.AUDIO,
    "audio/flac": MediaType.AUDIO,
    "video/mp4": MediaType.VIDEO,
    "video/quicktime": MediaType.VIDEO,
    "video/webm": MediaType.VIDEO,
    "video/x-matroska": MediaType.VIDEO,
}

EXTENSION_MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
    ".htm": "text/html",
    ".docx": DOCX_MIME,
    ".pptx": PPTX_MIME,
    ".xlsx": XLSX_MIME,
}

OFFICE_MIME_TYPES = frozenset({DOCX_MIME, PPTX_MIME, XLSX_MIME})


@dataclass(frozen=True, slots=True)
class DetectedType:
    media_type: MediaType
    mime_type: str


def normalize_mime_type(mime_type: str | None) -> str | None:
    if not mime_type:
        return None
    return mime_type.split(";", 1)[0].strip().lower() or None


def claimed_mime_type(declared: str | None, filename: str | None) -> str | None:
    by_extension = EXTENSION_MIME_TYPES.get(PurePath(filename).suffix.lower()) if filename else None
    normalized = normalize_mime_type(declared)
    if normalized in MIME_MEDIA_TYPES:
        return normalized
    return by_extension


def looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    for trim in range(UTF8_MAX_CONTINUATION + 1):
        try:
            head[: len(head) - trim].decode("utf-8")
        except UnicodeDecodeError:
            continue
        return True
    return False


def text_mime_type(head: bytes, claimed: str | None) -> str:
    if claimed is not None and MIME_MEDIA_TYPES[claimed] in {MediaType.TEXT, MediaType.HTML}:
        return claimed
    if head.lstrip()[:32].lower().startswith(HTML_MARKERS):
        return "text/html"
    return "text/plain"


def sniffed_mime_type(head: bytes, claimed: str | None) -> str | None:
    sniffed: str | None = filetype.guess_mime(head)
    if sniffed == ZIP_MIME and claimed in OFFICE_MIME_TYPES:
        return claimed
    if sniffed is None and looks_like_text(head):
        return text_mime_type(head, claimed)
    return sniffed


def detect(
    head: bytes, declared_mime: str | None = None, filename: str | None = None
) -> DetectedType:
    claimed = claimed_mime_type(declared_mime, filename)
    mime_type = sniffed_mime_type(head[:SNIFF_BYTES], claimed)
    media_type = MIME_MEDIA_TYPES.get(mime_type) if mime_type else None
    if mime_type is None or media_type is None:
        raise UnsupportedMediaTypeError(
            f"Unsupported content type: {mime_type or claimed or 'unknown'}"
        )
    return DetectedType(media_type, mime_type)
