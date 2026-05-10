"""Tests for language routing: full vs partial mode."""
from __future__ import annotations

import pytest

from llm_enricher.repository import _lang_to_mode


@pytest.mark.parametrize("lang,expected", [
    ("ru", "full"),
    ("en", "full"),
    ("de", "partial"),
    ("zh", "partial"),
    ("ar", "partial"),
    ("fr", "partial"),
    (None, "unknown"),
    ("und", "unknown"),
    ("", "unknown"),
])
def test_lang_to_mode(lang, expected):
    assert _lang_to_mode(lang) == expected


def test_other_lang_gets_partial_mode():
    result = _lang_to_mode("uk")
    assert result == "partial"


def test_ru_gets_full_mode():
    assert _lang_to_mode("ru") == "full"


def test_en_gets_full_mode():
    assert _lang_to_mode("en") == "full"
