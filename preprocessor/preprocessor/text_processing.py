from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional


URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@[A-Za-z0-9_]{1,64}")
HASHTAG_PATTERN = re.compile(r"#[A-Za-z0-9_]{1,64}")
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
PUNCTUATION_PATTERN = re.compile(r"[^\w\s%]", flags=re.UNICODE)
WHITESPACE_PATTERN = re.compile(r"\s+", flags=re.UNICODE)
CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04FF]")
LATIN_PATTERN = re.compile(r"[A-Za-z]")
SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?]+")


@dataclass
class PreprocessResult:
    cleaned_text: str
    normalized_text: str
    tokens: List[str]
    sentences_count: int
    word_count: int
    has_urls: bool
    has_mentions: bool
    has_hashtags: bool
    urls: List[str]
    mentions: List[str]
    hashtags: List[str]
    language: str


def _clean_entities(items: List[str]) -> List[str]:
    cleaned: List[str] = []
    for item in items:
        trimmed = item.rstrip(".,!?:;")
        if trimmed:
            cleaned.append(trimmed)
    return cleaned


def detect_language(text: str) -> str:
    if CYRILLIC_PATTERN.search(text):
        return "ru"
    if LATIN_PATTERN.search(text):
        return "en"
    return "ru"


def count_sentences(text: str) -> int:
    if not text.strip():
        return 0
    parts = [part for part in SENTENCE_SPLIT_PATTERN.split(text) if part.strip()]
    return max(1, len(parts))


def preprocess_text(text: Optional[str]) -> PreprocessResult:
    raw_text = text or ""
    urls = _clean_entities(URL_PATTERN.findall(raw_text))
    mentions = _clean_entities(MENTION_PATTERN.findall(raw_text))
    hashtags = _clean_entities(HASHTAG_PATTERN.findall(raw_text))

    stripped = URL_PATTERN.sub(" ", raw_text)
    stripped = MENTION_PATTERN.sub(" ", stripped)
    stripped = HASHTAG_PATTERN.sub(" ", stripped)
    stripped = EMOJI_PATTERN.sub(" ", stripped)
    stripped = stripped.lower()
    stripped = PUNCTUATION_PATTERN.sub(" ", stripped)
    stripped = WHITESPACE_PATTERN.sub(" ", stripped).strip()

    tokens = stripped.split() if stripped else []
    word_count = len(tokens)

    return PreprocessResult(
        cleaned_text=stripped,
        normalized_text=stripped,
        tokens=tokens,
        sentences_count=count_sentences(raw_text),
        word_count=word_count,
        has_urls=bool(urls),
        has_mentions=bool(mentions),
        has_hashtags=bool(hashtags),
        urls=urls,
        mentions=mentions,
        hashtags=hashtags,
        language=detect_language(raw_text),
    )
