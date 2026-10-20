from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.enums import ChunkModality

if TYPE_CHECKING:
    from PIL.Image import Image


@dataclass(frozen=True, slots=True)
class RawContent:
    data: bytes
    mime_type: str
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class TextSegment:
    text: str
    modality: ChunkModality = ChunkModality.TEXT
    page: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Frame:
    image: "Image"
    page: int | None = None
    timestamp_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Extraction:
    segments: list[TextSegment] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class Transcript:
    lines: list[TranscriptLine]
    duration_ms: int
    language: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    content: str
    token_count: int
    segment: TextSegment
