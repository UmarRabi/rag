from app.domain.content import Extraction, RawContent, TextSegment
from app.domain.enums import MediaType
from app.ingestion.cleaning import clean_text
from app.pipelines.base import extraction


class TextExtractor:
    media_type = MediaType.TEXT

    def extract(self, content: RawContent) -> Extraction:
        text = clean_text(content.data.decode("utf-8", errors="replace"))
        return extraction([TextSegment(text) if text else None])
