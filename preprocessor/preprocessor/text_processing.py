from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from collections import Counter
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "utm_campaign",
    "utm_content",
    "utm_id",
    "utm_medium",
    "utm_name",
    "utm_source",
    "utm_term",
    "ysclid",
}


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
    normalized_text_hash: Optional[str]
    simhash64: Optional[int]
    url_fingerprints: List[str]
    primary_url_fingerprint: Optional[str]


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


def normalize_url(url: str) -> Optional[str]:
    candidate = url.strip()
    if not candidate:
        return None
    if candidate.lower().startswith("www."):
        candidate = f"http://{candidate}"

    parts = urlsplit(candidate)
    if not parts.netloc:
        return None

    scheme = (parts.scheme or "http").lower()
    host = parts.hostname.lower() if parts.hostname else ""
    if not host:
        return None

    port = parts.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"

    path = parts.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
    ]
    query = urlencode(sorted(filtered_query))
    return urlunsplit((scheme, netloc, path, query, ""))


def fingerprint_text(text: Optional[str]) -> Optional[str]:
    value = (text or "").strip()
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprint_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _stable_u64(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def compute_simhash64(tokens: List[str]) -> Optional[int]:
    if not tokens:
        return None

    vector = [0] * 64
    for token, weight in Counter(tokens).items():
        hashed = _stable_u64(token)
        for bit in range(64):
            if hashed & (1 << bit):
                vector[bit] += weight
            else:
                vector[bit] -= weight

    result = 0
    for bit, value in enumerate(vector):
        if value > 0:
            result |= 1 << bit

    if result >= (1 << 63):
        return result - (1 << 64)
    return result


def fingerprint_urls(urls: List[str]) -> tuple[List[str], Optional[str]]:
    normalized_urls: List[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = normalize_url(url)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        normalized_urls.append(normalized)

    fingerprints = [fingerprint_url(url) for url in normalized_urls]
    primary = fingerprints[0] if fingerprints else None
    return fingerprints, primary


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
    url_fingerprints, primary_url_fingerprint = fingerprint_urls(urls)

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
        normalized_text_hash=fingerprint_text(stripped),
        simhash64=compute_simhash64(tokens),
        url_fingerprints=url_fingerprints,
        primary_url_fingerprint=primary_url_fingerprint,
    )
