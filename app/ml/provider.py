import threading
from collections.abc import Callable
from typing import Any, cast

from app.core.settings import Settings
from app.domain.interfaces import (
    ImageCaptioner,
    ImageEmbedder,
    LanguageDetector,
    OcrEngine,
    TextEmbedder,
    TokenCounter,
    Transcriber,
)
from app.ingestion.language import LinguaLanguageDetector
from app.ml.image import ClipImageEmbedder, Florence2Captioner
from app.ml.ocr import RapidOcrEngine
from app.ml.speech import WhisperTranscriber
from app.ml.text_embedding import FastEmbedTextEmbedder
from app.ml.tokens import HuggingFaceTokenCounter

WARM_UP_TEXT = "Warming up the models."


class LocalModels:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._loaded: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _once[T](self, name: str, load: Callable[[], T]) -> T:
        if name in self._loaded:
            return cast(T, self._loaded[name])
        with self._lock:
            if name not in self._loaded:
                self._loaded[name] = load()
            return cast(T, self._loaded[name])

    @property
    def text_embedder(self) -> TextEmbedder:
        settings = self._settings
        return self._once(
            "text_embedder",
            lambda: FastEmbedTextEmbedder(
                model_name=settings.text_embedding_model,
                model_file=settings.text_embedding_model_file,
                cache_dir=settings.model_cache_dir,
                query_prefix=settings.text_embedding_query_prefix,
                passage_prefix=settings.text_embedding_passage_prefix,
                batch_size=settings.embedding_batch_size,
            ),
        )

    @property
    def token_counter(self) -> TokenCounter:
        settings = self._settings
        return self._once(
            "token_counter",
            lambda: HuggingFaceTokenCounter.from_pretrained(
                settings.text_embedding_model,
                settings.model_cache_dir,
            ),
        )

    @property
    def language_detector(self) -> LanguageDetector:
        return self._once("language_detector", LinguaLanguageDetector)

    @property
    def ocr_engine(self) -> OcrEngine:
        return self._once("ocr_engine", RapidOcrEngine)

    @property
    def image_embedder(self) -> ImageEmbedder:
        settings = self._settings
        return self._once(
            "image_embedder",
            lambda: ClipImageEmbedder(
                image_model=settings.image_embedding_model,
                text_model=settings.image_text_embedding_model,
                cache_dir=settings.model_cache_dir,
            ),
        )

    @property
    def image_captioner(self) -> ImageCaptioner:
        settings = self._settings
        return self._once(
            "image_captioner",
            lambda: Florence2Captioner(
                model_name=settings.image_caption_model,
                cache_dir=settings.model_cache_dir,
                max_new_tokens=settings.image_caption_max_tokens,
            ),
        )

    @property
    def transcriber(self) -> Transcriber:
        settings = self._settings
        return self._once(
            "transcriber",
            lambda: WhisperTranscriber(
                model_name=settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                beam_size=settings.whisper_beam_size,
                cache_dir=settings.model_cache_dir,
            ),
        )

    def warm_up(self) -> None:
        self.text_embedder.embed_query(WARM_UP_TEXT)
        self.token_counter.count(WARM_UP_TEXT)
        self.language_detector.detect(WARM_UP_TEXT)
