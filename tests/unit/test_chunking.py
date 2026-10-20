import itertools

import pytest

from app.domain.content import TextSegment
from app.domain.enums import ChunkModality
from app.ingestion.chunking import PATH_SEPARATOR, Chunker, ChunkingPolicy, sections
from tests.fakes import WhitespaceTokenCounter

MAX_TOKENS = 10
OVERLAP_TOKENS = 4


@pytest.fixture
def chunker() -> Chunker:
    return Chunker(WhitespaceTokenCounter(), ChunkingPolicy(MAX_TOKENS, OVERLAP_TOKENS))


def sentences(count: int, words: int = 4) -> str:
    return " ".join(
        " ".join(f"s{index}w{word}" for word in range(words)) + "." for index in range(count)
    )


def test_short_text_is_a_single_chunk(chunker: Chunker) -> None:
    drafts = chunker.split([TextSegment("How do I reset my password?")])

    assert [draft.content for draft in drafts] == ["How do I reset my password?"]


def test_chunks_never_exceed_the_token_limit(chunker: Chunker) -> None:
    drafts = chunker.split([TextSegment(sentences(12))])

    assert len(drafts) > 1
    assert all(draft.token_count <= MAX_TOKENS for draft in drafts)


def test_consecutive_chunks_share_overlap(chunker: Chunker) -> None:
    drafts = chunker.split([TextSegment(sentences(6))])

    assert len(drafts) > 1
    for previous, current in itertools.pairwise(drafts):
        last_sentence = previous.content.rsplit(". ", 1)[-1]
        assert current.content.startswith(last_sentence.rstrip("."))


def test_every_sentence_is_kept(chunker: Chunker) -> None:
    text = sentences(8)
    drafts = chunker.split([TextSegment(text)])
    combined = " ".join(draft.content for draft in drafts)

    for sentence in text.split(". "):
        assert sentence.rstrip(".") in combined


def test_paragraph_breaks_are_preserved_inside_a_chunk(chunker: Chunker) -> None:
    drafts = chunker.split([TextSegment("Shipping info.\n\nReturns info.")])

    assert drafts[0].content == "Shipping info.\n\nReturns info."


def test_sentence_longer_than_the_limit_is_split_by_words(chunker: Chunker) -> None:
    drafts = chunker.split([TextSegment(" ".join(f"word{index}" for index in range(25)))])

    assert len(drafts) > 1
    assert all(draft.token_count <= MAX_TOKENS for draft in drafts)


def test_chunks_keep_their_segment_location(chunker: Chunker) -> None:
    segment = TextSegment("Page two text.", modality=ChunkModality.OCR, page=2)

    (draft,) = chunker.split([segment])

    assert draft.segment is segment


def test_overlap_must_be_smaller_than_the_limit() -> None:
    with pytest.raises(ValueError, match="overlap_tokens"):
        ChunkingPolicy(max_tokens=5, overlap_tokens=5)


ARTICLE = """# Account help

## Resetting your password

Click Forgot password on the sign-in page.

## Locked accounts

After five failed attempts your account is locked.

### Unlocking early

Reset your password to unlock it."""


def heading_path(*titles: str) -> str:
    return PATH_SEPARATOR.join(titles)


def test_each_section_becomes_its_own_chunk_under_its_heading_path() -> None:
    chunker = Chunker(WhitespaceTokenCounter(), ChunkingPolicy(max_tokens=50, overlap_tokens=5))

    chunks = [
        tuple(draft.content.split("\n\n", 1)) for draft in chunker.split([TextSegment(ARTICLE)])
    ]

    assert chunks == [
        (
            heading_path("Account help", "Resetting your password"),
            "Click Forgot password on the sign-in page.",
        ),
        (
            heading_path("Account help", "Locked accounts"),
            "After five failed attempts your account is locked.",
        ),
        (
            heading_path("Account help", "Locked accounts", "Unlocking early"),
            "Reset your password to unlock it.",
        ),
    ]


def test_long_sections_are_split_and_every_part_keeps_the_heading() -> None:
    chunker = Chunker(WhitespaceTokenCounter(), ChunkingPolicy(max_tokens=12, overlap_tokens=2))
    body = " ".join(f"Sentence {index} about refunds." for index in range(6))

    drafts = chunker.split([TextSegment(f"## Refunds\n\n{body}")])

    assert len(drafts) > 1
    assert all(draft.content.startswith("Refunds\n\n") for draft in drafts)
    assert all(draft.token_count <= 12 for draft in drafts)


def test_text_without_headings_is_chunked_as_before() -> None:
    chunker = Chunker(WhitespaceTokenCounter(), ChunkingPolicy(max_tokens=50, overlap_tokens=5))

    (draft,) = chunker.split([TextSegment("Plain text with no headings at all.")])

    assert draft.content == "Plain text with no headings at all."


def test_markdown_emphasis_is_removed_from_headings() -> None:
    assert sections("## **Bold** `code` heading\n\nBody")[0].path == ("Bold code heading",)
