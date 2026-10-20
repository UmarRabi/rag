import pytest

from app.core.errors import UnsupportedMediaTypeError
from app.core.settings import Settings
from app.domain.content import RawContent
from app.domain.enums import ChunkModality, MediaType
from app.pipelines.registry import ExtractorRegistry, default_registry
from tests.documents import (
    docx_document,
    html_document,
    pdf_document,
    pptx_document,
    xlsx_document,
)
from tests.fakes import FakeModels


@pytest.fixture
def models() -> FakeModels:
    return FakeModels()


@pytest.fixture
def registry(models: FakeModels) -> ExtractorRegistry:
    return default_registry(models, Settings(ocr_min_page_characters=10))


def extract(
    registry: ExtractorRegistry, media_type: MediaType, data: bytes
) -> list[tuple[str, ChunkModality, int | None]]:
    segments = (
        registry.get(media_type).extract(RawContent(data, "application/octet-stream")).segments
    )
    return [(segment.text, segment.modality, segment.page) for segment in segments]


def test_pdf_pages_become_numbered_segments(registry: ExtractorRegistry) -> None:
    pages = extract(registry, MediaType.PDF, pdf_document("Page one content.", "Page two content."))

    assert pages == [
        ("Page one content.", ChunkModality.TEXT, 1),
        ("Page two content.", ChunkModality.TEXT, 2),
    ]


def test_pdf_pages_without_text_are_ocred(registry: ExtractorRegistry, models: FakeModels) -> None:
    pages = extract(registry, MediaType.PDF, pdf_document("Typed page content.", ""))

    assert models.ocr_engine.calls == 1
    assert pages[1] == ("Scanned invoice\nTotal due 120 USD", ChunkModality.OCR, 2)


def test_blank_pdf_pages_without_ocr_text_are_skipped(
    registry: ExtractorRegistry,
    models: FakeModels,
) -> None:
    models.ocr_engine.lines = []

    assert extract(registry, MediaType.PDF, pdf_document("", "Second page content.")) == [
        ("Second page content.", ChunkModality.TEXT, 2),
    ]


def test_docx_keeps_headings_and_tables_in_order(registry: ExtractorRegistry) -> None:
    ((text, _, page),) = extract(registry, MediaType.DOCX, docx_document())

    assert (
        text
        == "# Returns policy\n\nItems can be returned within 30 days.\n\nItem | Days\nRouter | 14"
    )
    assert page is None


def test_pptx_slides_include_speaker_notes(registry: ExtractorRegistry) -> None:
    slides = extract(registry, MediaType.PPTX, pptx_document())

    assert [page for _, _, page in slides] == [1, 2]
    assert "Welcome to the team" in slides[0][0]
    assert "Mention the gym discount" in slides[1][0]


def test_xlsx_rows_are_labelled_with_their_headers(registry: ExtractorRegistry) -> None:
    ((text, _, page),) = extract(registry, MediaType.XLSX, xlsx_document())

    assert text == "Sheet: Prices\n\nProduct: Router X | Price: 120\n\nProduct: Router Y"
    assert page == 1


def test_html_keeps_the_article_and_drops_navigation(registry: ExtractorRegistry) -> None:
    ((text, _, _),) = extract(registry, MediaType.HTML, html_document())

    assert "Hold the reset button for ten seconds" in text
    assert "Pricing" not in text
    assert "Copyright" not in text


def test_every_media_type_has_an_extractor(registry: ExtractorRegistry) -> None:
    assert all(registry.supports(media_type) for media_type in MediaType)


def test_registry_rejects_media_types_without_an_extractor() -> None:
    empty = ExtractorRegistry([])

    assert not empty.supports(MediaType.AUDIO)
    with pytest.raises(UnsupportedMediaTypeError):
        empty.get(MediaType.AUDIO)
