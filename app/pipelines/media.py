import io
from collections.abc import Iterator
from dataclasses import dataclass

from app.domain.content import Extraction, Frame, RawContent, TextSegment, Transcript
from app.domain.enums import ChunkModality, MediaType
from app.domain.interfaces import ModelProvider, TokenCounter
from app.ingestion.cleaning import clean_text
from app.ml.optional import optional_module

MEDIA_GROUP = "media"
MILLISECONDS = 1000


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration_ms: int | None
    has_audio: bool


@dataclass(frozen=True, slots=True)
class KeyframePolicy:
    interval_seconds: float
    max_frames: int
    with_ocr: bool


def probe(data: bytes) -> MediaInfo:
    av = optional_module("av", MEDIA_GROUP)
    with av.open(io.BytesIO(data)) as container:
        duration = container.duration
        return MediaInfo(
            duration_ms=round(duration / av.time_base * MILLISECONDS) if duration else None,
            has_audio=bool(container.streams.audio),
        )


def sample_keyframes(data: bytes, policy: KeyframePolicy) -> list[Frame]:
    av = optional_module("av", MEDIA_GROUP)
    frames: list[Frame] = []
    next_due = 0.0
    with av.open(io.BytesIO(data)) as container:
        if not container.streams.video:
            return frames
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        for decoded in container.decode(stream):
            if decoded.time is None or decoded.time < next_due:
                continue
            frames.append(
                Frame(decoded.to_image(), timestamp_ms=round(decoded.time * MILLISECONDS))
            )
            next_due = decoded.time + policy.interval_seconds
            if len(frames) >= policy.max_frames:
                break
    return frames


def transcript_segments(
    transcript: Transcript,
    tokens: TokenCounter,
    max_tokens: int,
) -> list[TextSegment]:
    segments: list[TextSegment] = []
    group: list[str] = []
    start_ms = end_ms = 0
    size = 0
    for line in transcript.lines:
        line_tokens = tokens.count(line.text)
        if group and size + line_tokens > max_tokens:
            segments.append(transcript_segment(group, start_ms, end_ms))
            group, size = [], 0
        if not group:
            start_ms = line.start_ms
        group.append(line.text)
        end_ms = line.end_ms
        size += line_tokens
    if group:
        segments.append(transcript_segment(group, start_ms, end_ms))
    return segments


def transcript_segment(lines: list[str], start_ms: int, end_ms: int) -> TextSegment:
    return TextSegment(
        clean_text(" ".join(lines)),
        modality=ChunkModality.TRANSCRIPT,
        start_ms=start_ms,
        end_ms=end_ms,
    )


class AudioExtractor:
    media_type = MediaType.AUDIO

    def __init__(self, models: ModelProvider, max_tokens: int) -> None:
        self._models = models
        self._max_tokens = max_tokens

    def extract(self, content: RawContent) -> Extraction:
        transcript = self._models.transcriber.transcribe(content.data)
        segments = transcript_segments(transcript, self._models.token_counter, self._max_tokens)
        return Extraction(segments, duration_ms=transcript.duration_ms)


class VideoExtractor:
    media_type = MediaType.VIDEO

    def __init__(self, models: ModelProvider, max_tokens: int, policy: KeyframePolicy) -> None:
        self._models = models
        self._max_tokens = max_tokens
        self._policy = policy

    def extract(self, content: RawContent) -> Extraction:
        info = probe(content.data)
        frames = sample_keyframes(content.data, self._policy)
        segments = [*self._spoken(content.data, info), *self._visual(frames)]
        return Extraction(segments, frames, duration_ms=info.duration_ms)

    def _spoken(self, data: bytes, info: MediaInfo) -> list[TextSegment]:
        if not info.has_audio:
            return []
        transcript = self._models.transcriber.transcribe(data)
        return transcript_segments(transcript, self._models.token_counter, self._max_tokens)

    def _visual(self, frames: list[Frame]) -> Iterator[TextSegment]:
        for frame in frames:
            timestamp = frame.timestamp_ms
            caption = clean_text(self._models.image_captioner.caption(frame.image))
            if caption:
                yield TextSegment(
                    caption,
                    modality=ChunkModality.CAPTION,
                    start_ms=timestamp,
                    end_ms=timestamp,
                )
            if not self._policy.with_ocr:
                continue
            text = clean_text("\n".join(self._models.ocr_engine.read(frame.image)))
            if text:
                yield TextSegment(
                    text, modality=ChunkModality.OCR, start_ms=timestamp, end_ms=timestamp
                )
