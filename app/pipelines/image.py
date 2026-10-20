import io

from PIL import Image, ImageOps

from app.domain.content import Extraction, Frame, RawContent, TextSegment
from app.domain.enums import ChunkModality, MediaType
from app.domain.interfaces import ModelProvider
from app.ingestion.cleaning import clean_text
from app.pipelines.base import extraction


def load_image(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as source:
        source.seek(0)
        return ImageOps.exif_transpose(source).convert("RGB")


class ImageExtractor:
    media_type = MediaType.IMAGE

    def __init__(self, models: ModelProvider) -> None:
        self._models = models

    def extract(self, content: RawContent) -> Extraction:
        image = load_image(content.data)
        text = clean_text("\n".join(self._models.ocr_engine.read(image)))
        caption = clean_text(self._models.image_captioner.caption(image))
        segments = extraction(
            [
                TextSegment(caption, modality=ChunkModality.CAPTION) if caption else None,
                TextSegment(text, modality=ChunkModality.OCR) if text else None,
            ],
        ).segments
        return Extraction(segments, [Frame(image)])
