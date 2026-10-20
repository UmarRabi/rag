import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app.domain.content import ChunkDraft, TextSegment
from app.domain.interfaces import TokenCounter

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
EMPHASIS = re.compile(r"[*_`]+")
PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
SENTENCE_BREAK = re.compile(r"(?<=[.!?;\u3002\uff01\uff1f\uff1b])\s+|\n")
WORD_BREAK = re.compile(r"\s+")
PATH_SEPARATOR = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "
MIN_BODY_TOKENS = 32


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    max_tokens: int
    overlap_tokens: int

    def __post_init__(self) -> None:
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be smaller than max_tokens")


@dataclass(frozen=True, slots=True)
class Unit:
    text: str
    tokens: int
    separator: str


@dataclass(frozen=True, slots=True)
class Section:
    path: tuple[str, ...]
    body: str

    @property
    def heading(self) -> str:
        return PATH_SEPARATOR.join(self.path)


def sections(text: str) -> list[Section]:
    found: list[Section] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            found.append(Section(tuple(title for _, title in stack), body))
        lines.clear()

    for line in text.split("\n"):
        match = HEADING.match(line.strip())
        if match is None:
            lines.append(line)
            continue
        flush()
        level = len(match.group(1))
        stack[:] = [entry for entry in stack if entry[0] < level]
        stack.append((level, EMPHASIS.sub("", match.group(2)).strip()))
    flush()
    return found


class Chunker:
    def __init__(self, tokens: TokenCounter, policy: ChunkingPolicy) -> None:
        self._tokens = tokens
        self._policy = policy

    def split(self, segments: Iterable[TextSegment]) -> list[ChunkDraft]:
        return [draft for segment in segments for draft in self._split_segment(segment)]

    def _split_segment(self, segment: TextSegment) -> Iterator[ChunkDraft]:
        for section in sections(segment.text):
            heading = section.heading
            budget = self._body_budget(heading)
            for window in self._windows(list(self._units(section.body, budget)), budget):
                body = window[0].text + "".join(unit.separator + unit.text for unit in window[1:])
                content = f"{heading}\n\n{body}" if heading else body
                yield ChunkDraft(
                    content=content,
                    token_count=self._tokens.count(content),
                    segment=segment,
                )

    def _body_budget(self, heading: str) -> int:
        if not heading:
            return self._policy.max_tokens
        remaining = self._policy.max_tokens - self._tokens.count(heading)
        return max(remaining, min(MIN_BODY_TOKENS, self._policy.max_tokens // 2))

    def _units(self, text: str, budget: int) -> Iterator[Unit]:
        for paragraph in self._parts(PARAGRAPH_BREAK, text):
            yield from self._fitted(paragraph, "\n\n", (SENTENCE_BREAK, WORD_BREAK), budget)

    def _fitted(
        self,
        text: str,
        separator: str,
        finer_breaks: tuple[re.Pattern[str], ...],
        budget: int,
    ) -> Iterator[Unit]:
        tokens = self._tokens.count(text)
        if tokens <= budget or not finer_breaks:
            yield Unit(text, tokens, separator)
            return

        pattern, *rest = finer_breaks
        parts = self._parts(pattern, text)
        if len(parts) == 1:
            yield from self._fitted(text, separator, tuple(rest), budget)
            return

        for index, part in enumerate(parts):
            yield from self._fitted(part, separator if index == 0 else " ", tuple(rest), budget)

    def _windows(self, units: list[Unit], budget: int) -> Iterator[list[Unit]]:
        window: list[Unit] = []
        size = 0
        for unit in units:
            if window and size + unit.tokens > budget:
                yield window
                window = self._overlap(window, unit.tokens, budget)
                size = sum(item.tokens for item in window)
            window.append(unit)
            size += unit.tokens
        if window:
            yield window

    def _overlap(self, window: list[Unit], incoming_tokens: int, budget: int) -> list[Unit]:
        allowance = min(self._policy.overlap_tokens, budget - incoming_tokens)
        carried: list[Unit] = []
        used = 0
        for unit in reversed(window):
            if used + unit.tokens > allowance:
                break
            carried.insert(0, unit)
            used += unit.tokens
        return carried

    @staticmethod
    def _parts(pattern: re.Pattern[str], text: str) -> list[str]:
        return [part.strip() for part in pattern.split(text) if part.strip()]
