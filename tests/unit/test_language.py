import pytest

from app.ingestion.language import dominant_language, text_search_config


@pytest.mark.parametrize(
    ("language", "config"),
    [("en", "english"), ("fr", "french"), ("pt", "portuguese"), ("yo", "simple"), (None, "simple")],
)
def test_text_search_config_falls_back_to_simple(language: str | None, config: str) -> None:
    assert text_search_config(language) == config


def test_dominant_language_ignores_unknown_chunks() -> None:
    assert dominant_language(["fr", None, "en", "fr"]) == "fr"


def test_dominant_language_is_none_without_detections() -> None:
    assert dominant_language([None, None]) is None
