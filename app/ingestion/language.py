from collections import Counter
from collections.abc import Iterable

from lingua import LanguageDetectorBuilder

SIMPLE_TEXT_SEARCH_CONFIG = "simple"

TEXT_SEARCH_CONFIGS = {
    "ar": "arabic",
    "da": "danish",
    "de": "german",
    "el": "greek",
    "en": "english",
    "es": "spanish",
    "fi": "finnish",
    "fr": "french",
    "ga": "irish",
    "hu": "hungarian",
    "id": "indonesian",
    "it": "italian",
    "lt": "lithuanian",
    "nl": "dutch",
    "no": "norwegian",
    "nb": "norwegian",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sv": "swedish",
    "ta": "tamil",
    "tr": "turkish",
}


def text_search_config(language: str | None) -> str:
    if language is None:
        return SIMPLE_TEXT_SEARCH_CONFIG
    return TEXT_SEARCH_CONFIGS.get(language, SIMPLE_TEXT_SEARCH_CONFIG)


def dominant_language(languages: Iterable[str | None]) -> str | None:
    counts = Counter(language for language in languages if language)
    return counts.most_common(1)[0][0] if counts else None


class LinguaLanguageDetector:
    def __init__(self, minimum_relative_distance: float = 0.1) -> None:
        self._detector = (
            LanguageDetectorBuilder.from_all_languages()
            .with_low_accuracy_mode()
            .with_minimum_relative_distance(minimum_relative_distance)
            .build()
        )

    def detect(self, text: str) -> str | None:
        language = self._detector.detect_language_of(text)
        if language is None:
            return None
        return language.iso_code_639_1.name.lower()
