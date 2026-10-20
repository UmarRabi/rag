import trafilatura

from app.domain.content import Extraction, RawContent, TextSegment
from app.domain.enums import MediaType
from app.ingestion.cleaning import clean_text
from app.pipelines.base import extraction


class HtmlExtractor:
    media_type = MediaType.HTML

    def extract(self, content: RawContent) -> Extraction:
        main_content = trafilatura.extract(
            content.data,
            include_tables=True,
            include_comments=False,
            favor_recall=True,
            output_format="markdown",
            include_formatting=True,
        )
        text = clean_text(main_content or trafilatura.html2txt(content.data) or "")
        return extraction([TextSegment(text) if text else None])
