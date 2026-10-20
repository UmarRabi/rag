from app.ingestion.cleaning import clean_text


def test_collapses_horizontal_whitespace_and_trims_lines() -> None:
    assert clean_text("  Reset \t your\u00a0 password  ") == "Reset your password"


def test_keeps_paragraphs_but_limits_blank_lines() -> None:
    assert clean_text("First\r\n\r\n\r\n\r\nSecond\rThird") == "First\n\nSecond\nThird"


def test_removes_control_and_zero_width_characters() -> None:
    assert clean_text("pass\u200bword\x00\ufeff") == "password"


def test_normalizes_unicode_composition() -> None:
    assert clean_text("cafe\N{COMBINING ACUTE ACCENT}") == "caf\N{LATIN SMALL LETTER E WITH ACUTE}"


def test_whitespace_only_text_becomes_empty() -> None:
    assert clean_text(" \n\t\u200b ") == ""
