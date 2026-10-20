import pytest

from app.core.settings import Settings
from app.domain.content import Extraction, RawContent, Transcript, TranscriptLine
from app.domain.enums import ChunkModality, MediaType
from app.pipelines.media import KeyframePolicy, probe, sample_keyframes, transcript_segments
from app.pipelines.registry import ExtractorRegistry, default_registry
from tests.documents import mp4_video, png_image, wav_audio
from tests.fakes import FakeModels, WhitespaceTokenCounter, nearest_colour

EVERY_FOUR_SECONDS = KeyframePolicy(interval_seconds=4.0, max_frames=10, with_ocr=False)


@pytest.fixture
def models() -> FakeModels:
    return FakeModels()


@pytest.fixture
def registry(models: FakeModels) -> ExtractorRegistry:
    return default_registry(
        models,
        Settings(chunk_max_tokens=12, video_keyframe_seconds=4.0, video_keyframe_ocr=True),
    )


def extract(registry: ExtractorRegistry, media_type: MediaType, data: bytes) -> Extraction:
    return registry.get(media_type).extract(RawContent(data, "application/octet-stream"))


def test_transcript_lines_are_grouped_up_to_the_token_budget() -> None:
    transcript = Transcript(
        [
            TranscriptLine("one two three", 0, 1000),
            TranscriptLine("four five six", 1000, 2000),
            TranscriptLine("seven eight nine", 2000, 3000),
        ],
        duration_ms=3000,
    )

    segments = transcript_segments(transcript, WhitespaceTokenCounter(), max_tokens=6)

    assert [(segment.text, segment.start_ms, segment.end_ms) for segment in segments] == [
        ("one two three four five six", 0, 2000),
        ("seven eight nine", 2000, 3000),
    ]
    assert {segment.modality for segment in segments} == {ChunkModality.TRANSCRIPT}


def test_keyframes_are_sampled_at_the_interval() -> None:
    frames = sample_keyframes(mp4_video(["red", "blue", "green"]), EVERY_FOUR_SECONDS)

    assert [frame.timestamp_ms for frame in frames] == [0, 4000, 8000]
    assert [nearest_colour(frame.image.getpixel((5, 5))) for frame in frames] == [
        "red",
        "blue",
        "green",
    ]


def test_keyframes_stop_at_the_limit() -> None:
    policy = KeyframePolicy(interval_seconds=1.0, max_frames=2, with_ocr=False)

    assert len(sample_keyframes(mp4_video(["red", "blue", "green"]), policy)) == 2


def test_probe_reports_duration_and_audio() -> None:
    silent, voiced = probe(mp4_video(["red", "blue"])), probe(mp4_video(["red"], with_audio=True))

    assert (silent.duration_ms, silent.has_audio) == (8000, False)
    assert voiced.has_audio


def test_images_become_a_caption_ocr_text_and_one_frame(registry: ExtractorRegistry) -> None:
    extraction = extract(registry, MediaType.IMAGE, png_image("red"))

    assert [(segment.modality, segment.text) for segment in extraction.segments] == [
        (ChunkModality.CAPTION, "A product photo on a white desk"),
        (ChunkModality.OCR, "Scanned invoice\nTotal due 120 USD"),
    ]
    assert len(extraction.frames) == 1


def test_audio_becomes_timestamped_transcript_segments(registry: ExtractorRegistry) -> None:
    extraction = extract(registry, MediaType.AUDIO, wav_audio())

    segments = extraction.segments
    assert [segment.start_ms for segment in segments] == [0, 2400, 6800]
    assert segments[0].text.startswith("Thanks for calling Acme support.")
    assert extraction.duration_ms == 9500


def test_video_combines_keyframes_captions_and_speech(
    registry: ExtractorRegistry,
    models: FakeModels,
) -> None:
    extraction = extract(registry, MediaType.VIDEO, mp4_video(["red", "blue"], with_audio=True))

    frames = extraction.frames
    captions = [
        segment for segment in extraction.segments if segment.modality is ChunkModality.CAPTION
    ]
    assert [frame.timestamp_ms for frame in frames] == [0, 4000]
    assert [caption.start_ms for caption in captions] == [0, 4000]
    assert models.transcriber.calls == 1


def test_silent_video_is_not_transcribed(registry: ExtractorRegistry, models: FakeModels) -> None:
    extract(registry, MediaType.VIDEO, mp4_video(["red"]))

    assert models.transcriber.calls == 0
