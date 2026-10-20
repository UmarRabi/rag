import io
from pathlib import Path

import numpy as np

from app.domain.content import Transcript, TranscriptLine
from app.ml.optional import optional_module

MEDIA_GROUP = "media"
MILLISECONDS = 1000
SAMPLE_RATE = 16_000


def decode_audio(media: bytes, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    av = optional_module("av", MEDIA_GROUP)
    resampler = av.AudioResampler(format="flt", layout="mono", rate=sample_rate)
    chunks: list[np.ndarray] = []
    with av.open(io.BytesIO(media)) as container:
        if not container.streams.audio:
            return np.zeros(0, dtype=np.float32)
        for frame in container.decode(container.streams.audio[0]):
            chunks.extend(
                resampled.to_ndarray().reshape(-1) for resampled in resampler.resample(frame)
            )
        chunks.extend(resampled.to_ndarray().reshape(-1) for resampled in resampler.resample(None))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, dtype=np.float32)


class WhisperTranscriber:
    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        compute_type: str,
        beam_size: int,
        cache_dir: Path,
    ) -> None:
        faster_whisper = optional_module("faster_whisper", MEDIA_GROUP)
        self._beam_size = beam_size
        self._model = faster_whisper.WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=str(cache_dir),
        )

    def transcribe(self, media: bytes) -> Transcript:
        samples = decode_audio(media)
        duration_ms = round(len(samples) / SAMPLE_RATE * MILLISECONDS)
        if not len(samples):
            return Transcript(lines=[], duration_ms=duration_ms)

        segments, info = self._model.transcribe(samples, beam_size=self._beam_size, vad_filter=True)
        lines = [
            TranscriptLine(
                text=segment.text.strip(),
                start_ms=round(segment.start * MILLISECONDS),
                end_ms=round(segment.end * MILLISECONDS),
            )
            for segment in segments
            if segment.text.strip()
        ]
        return Transcript(lines=lines, duration_ms=duration_ms, language=info.language)
