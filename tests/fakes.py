import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.db.models.vectors import IMAGE_EMBEDDING_DIMENSIONS, TEXT_EMBEDDING_DIMENSIONS
from app.domain.content import Transcript, TranscriptLine


class WhitespaceTokenCounter:
    def count(self, text: str) -> int:
        return len(text.split())


def seeded_vector(seed_text: str, dimensions: int) -> list[float]:
    seed = hashlib.sha256(seed_text.encode()).digest()
    values = [seed[index % len(seed)] - 127.5 for index in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


class HashingEmbedder:
    model_name = "test/hashing-embedder"

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        return seeded_vector(text, TEXT_EMBEDDING_DIMENSIONS)


COLOURS = {"red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255), "white": (255, 255, 255)}


class ColourImageEmbedder:
    model_name = "test/colour-embedder"

    def embed_images(self, images: Sequence[Any]) -> list[list[float]]:
        return [
            self._vector(nearest_colour(image.convert("RGB").getpixel((0, 0)))) for image in images
        ]

    def embed_text(self, text: str) -> list[float]:
        named = next((name for name in COLOURS if name in text.lower()), text)
        return self._vector(named)

    @staticmethod
    def _vector(seed: str) -> list[float]:
        return seeded_vector(seed, IMAGE_EMBEDDING_DIMENSIONS)


def nearest_colour(pixel: Any) -> str:
    return min(
        COLOURS,
        key=lambda name: sum((a - b) ** 2 for a, b in zip(COLOURS[name], pixel, strict=True)),
    )


@dataclass
class FixedCaptioner:
    caption_text: str = "A product photo on a white desk"

    def caption(self, image: Any) -> str:
        return self.caption_text


@dataclass
class ScriptedTranscriber:
    lines: list[TranscriptLine] = field(
        default_factory=lambda: [
            TranscriptLine("Thanks for calling Acme support.", 0, 2400),
            TranscriptLine("To reset the router hold the button for ten seconds.", 2400, 6800),
            TranscriptLine("The light turns green when it is ready.", 6800, 9500),
        ],
    )
    duration_ms: int = 9500
    calls: int = 0

    def transcribe(self, media: bytes) -> Transcript:
        self.calls += 1
        return Transcript(list(self.lines), self.duration_ms, "en")


class FailingEmbedder(HashingEmbedder):
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("Embedding model unavailable")


@dataclass
class FixedLanguageDetector:
    language: str | None = "en"

    def detect(self, text: str) -> str | None:
        return self.language


@dataclass
class FakeOcrEngine:
    lines: list[str] = field(default_factory=lambda: ["Scanned invoice", "Total due 120 USD"])
    calls: int = 0

    def read(self, image: Any) -> list[str]:
        self.calls += 1
        return list(self.lines)


@dataclass
class FakeModels:
    text_embedder: HashingEmbedder = field(default_factory=HashingEmbedder)
    token_counter: WhitespaceTokenCounter = field(default_factory=WhitespaceTokenCounter)
    language_detector: FixedLanguageDetector = field(default_factory=FixedLanguageDetector)
    ocr_engine: FakeOcrEngine = field(default_factory=FakeOcrEngine)
    image_embedder: ColourImageEmbedder = field(default_factory=ColourImageEmbedder)
    image_captioner: FixedCaptioner = field(default_factory=FixedCaptioner)
    transcriber: ScriptedTranscriber = field(default_factory=ScriptedTranscriber)
