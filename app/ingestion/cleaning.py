import re
import unicodedata

INVISIBLE_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200d\u2060\ufeff]")
HORIZONTAL_WHITESPACE = re.compile(r"[ \t\u00a0\u3000]+")
EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    visible = INVISIBLE_CHARACTERS.sub("", normalized)
    lines = (HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in visible.split("\n"))
    return EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
