from collections.abc import Iterable

from app.core.errors import UnsupportedMediaTypeError
from app.core.settings import Settings
from app.domain.enums import MediaType
from app.domain.interfaces import Extractor, ModelProvider
from app.pipelines.html import HtmlExtractor
from app.pipelines.image import ImageExtractor
from app.pipelines.media import AudioExtractor, KeyframePolicy, VideoExtractor
from app.pipelines.office import DocxExtractor, PptxExtractor, XlsxExtractor
from app.pipelines.pdf import PdfExtractor
from app.pipelines.text import TextExtractor


class ExtractorRegistry:
    def __init__(self, extractors: Iterable[Extractor]) -> None:
        self._extractors = {extractor.media_type: extractor for extractor in extractors}

    def supports(self, media_type: MediaType) -> bool:
        return media_type in self._extractors

    def get(self, media_type: MediaType) -> Extractor:
        extractor = self._extractors.get(media_type)
        if extractor is None:
            raise UnsupportedMediaTypeError(f"{media_type} content is not supported yet")
        return extractor


def keyframe_policy(settings: Settings) -> KeyframePolicy:
    return KeyframePolicy(
        interval_seconds=settings.video_keyframe_seconds,
        max_frames=settings.video_max_keyframes,
        with_ocr=settings.video_keyframe_ocr,
    )


def default_registry(models: ModelProvider, settings: Settings) -> ExtractorRegistry:
    return ExtractorRegistry(
        [
            TextExtractor(),
            HtmlExtractor(),
            PdfExtractor(models, settings.ocr_min_page_characters, settings.ocr_render_scale),
            DocxExtractor(),
            PptxExtractor(),
            XlsxExtractor(),
            ImageExtractor(models),
            AudioExtractor(models, settings.chunk_max_tokens),
            VideoExtractor(models, settings.chunk_max_tokens, keyframe_policy(settings)),
        ],
    )
