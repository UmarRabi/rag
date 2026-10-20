import pytest

from app.core.errors import UnsupportedMediaTypeError
from app.domain.enums import MediaType
from app.pipelines.detection import detect
from tests.documents import (
    DOCX_MIME,
    XLSX_MIME,
    docx_document,
    html_document,
    pdf_document,
    png_image,
    xlsx_document,
)


@pytest.mark.parametrize(
    ("data", "declared", "filename", "media_type"),
    [
        (pdf_document("Hello"), None, None, MediaType.PDF),
        (pdf_document("Hello"), "text/plain", "notes.txt", MediaType.PDF),
        (png_image(), None, None, MediaType.IMAGE),
        (docx_document(), None, "letter.docx", MediaType.DOCX),
        (docx_document(), DOCX_MIME, None, MediaType.DOCX),
        (xlsx_document(), XLSX_MIME, "prices.xlsx", MediaType.XLSX),
        (html_document(), None, None, MediaType.HTML),
        (b"# Title\n\nBody", "text/markdown", "readme.md", MediaType.TEXT),
        (b"plain words", None, None, MediaType.TEXT),
        ("caf\N{LATIN SMALL LETTER E WITH ACUTE}".encode(), None, None, MediaType.TEXT),
    ],
    ids=[
        "pdf",
        "pdf-mislabelled-as-text",
        "png",
        "docx-by-extension",
        "docx-by-declared-type",
        "xlsx",
        "html",
        "markdown",
        "plain-text",
        "utf8-text",
    ],
)
def test_detects_media_type_from_content(
    data: bytes,
    declared: str | None,
    filename: str | None,
    media_type: MediaType,
) -> None:
    assert detect(data, declared, filename).media_type is media_type


def test_declared_text_subtype_is_kept_for_text_content() -> None:
    assert detect(b"a,b\n1,2", "text/csv").mime_type == "text/csv"


def test_utf8_cut_mid_character_is_still_text() -> None:
    head = "na\N{LATIN SMALL LETTER I WITH DIAERESIS}ve".encode()[:3]

    assert detect(head).media_type is MediaType.TEXT


@pytest.mark.parametrize(
    ("data", "declared"),
    [
        (bytes(range(256)), None),
        (b"PK\x03\x04" + b"\x00" * 64, "application/zip"),
    ],
    ids=["random-binary", "plain-zip"],
)
def test_unknown_or_unsupported_binary_is_rejected(data: bytes, declared: str | None) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        detect(data, declared)
