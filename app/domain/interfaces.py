from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from app.domain.content import Extraction, RawContent, Transcript
from app.domain.enums import MediaType

if TYPE_CHECKING:
    from PIL.Image import Image


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class TextEmbedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class ImageEmbedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed_images(self, images: Sequence["Image"]) -> list[list[float]]: ...

    def embed_text(self, text: str) -> list[float]: ...


class ImageCaptioner(Protocol):
    def caption(self, image: "Image") -> str: ...


class LanguageDetector(Protocol):
    def detect(self, text: str) -> str | None: ...


class OcrEngine(Protocol):
    def read(self, image: "Image") -> list[str]: ...


class Transcriber(Protocol):
    def transcribe(self, media: bytes) -> Transcript: ...


class Extractor(Protocol):
    @property
    def media_type(self) -> MediaType: ...

    def extract(self, content: RawContent) -> Extraction: ...


class ModelProvider(Protocol):
    @property
    def text_embedder(self) -> TextEmbedder: ...

    @property
    def token_counter(self) -> TokenCounter: ...

    @property
    def language_detector(self) -> LanguageDetector: ...

    @property
    def ocr_engine(self) -> OcrEngine: ...

    @property
    def image_embedder(self) -> ImageEmbedder: ...

    @property
    def image_captioner(self) -> ImageCaptioner: ...

    @property
    def transcriber(self) -> Transcriber: ...
