from collections.abc import Iterable

from app.domain.content import Extraction, TextSegment


def extraction(segments: Iterable[TextSegment | None]) -> Extraction:
    return Extraction([segment for segment in segments if segment is not None])
