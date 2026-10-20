import pypdfium2 as pdfium

from app.domain.content import Extraction, RawContent, TextSegment
from app.domain.enums import ChunkModality, MediaType
from app.domain.interfaces import ModelProvider
from app.ingestion.cleaning import clean_text
from app.pipelines.base import extraction


class PdfExtractor:
    media_type = MediaType.PDF

    def __init__(
        self, models: ModelProvider, min_page_characters: int, render_scale: float
    ) -> None:
        self._models = models
        self._min_page_characters = min_page_characters
        self._render_scale = render_scale

    def extract(self, content: RawContent) -> Extraction:
        document = pdfium.PdfDocument(content.data)
        try:
            segments = (self._page(page, number) for number, page in enumerate(document, start=1))
            return extraction(segments)
        finally:
            document.close()

    def _page(self, page: pdfium.PdfPage, number: int) -> TextSegment | None:
        text_page = page.get_textpage()
        try:
            text = clean_text(text_page.get_text_bounded())
        finally:
            text_page.close()

        if len(text) >= self._min_page_characters:
            return TextSegment(text, page=number)

        scanned = self._ocr(page)
        if scanned:
            return TextSegment(scanned, modality=ChunkModality.OCR, page=number)
        return TextSegment(text, page=number) if text else None

    def _ocr(self, page: pdfium.PdfPage) -> str:
        bitmap = page.render(scale=self._render_scale)
        try:
            lines = self._models.ocr_engine.read(bitmap.to_pil())
        finally:
            bitmap.close()
        return clean_text("\n".join(lines))
