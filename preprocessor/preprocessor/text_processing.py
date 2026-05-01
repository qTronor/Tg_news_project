from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from collections import Counter
from typing import Iterable, List, Optional
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
    "\U0001F1E6-\U0001F1FF"
    "\U00002600-\U000026FF"
    "\U00002300-\U000023FF"
    "]+",
    flags=re.UNICODE,
)
EMOJI_MODIFIER_PATTERN = re.compile(r"[\ufe0e\ufe0f\u200d\U0001F3FB-\U0001F3FF]+")
PUNCTUATION_PATTERN = re.compile(r"[^\w\s%]", flags=re.UNICODE)
WHITESPACE_PATTERN = re.compile(r"\s+", flags=re.UNICODE)
LINE_NOISE_PREFIX_PATTERN = re.compile(
    r"^\s*(?:[^\w\s]+\s*)?"
    r"(?:реклама|на правах рекламы|erid\b|ad\b|партнерский материал\b)",
    re.IGNORECASE,
)
PROMO_LINE_PATTERN = re.compile(
    r"\b("
    r"подпис(?:аться|ывайтесь|ывайся|ываемся)"
    r"|подробнее\s+в\s+подписке"
    r"|читайте\s+нас"
    r"|наш\s+канал"
    r"|канал\s+\S+\s+в\s+max"
    r"|приложени[ея]\s+\S+\s+для\s+(?:ios|android)"
    r"|прислать\s+новост"
    r"|присылайте\s+новост"
    r")\b",
    re.IGNORECASE,
)
TELEGRAM_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/\S+",
    re.IGNORECASE,
)
CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04FF]")
LATIN_PATTERN = re.compile(r"[A-Za-z]")
LETTER_PATTERN = re.compile(r"[^\W\d_]", flags=re.UNICODE)
SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?]+")
ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF]")
CJK_PATTERN = re.compile(r"[\u3400-\u9FFF]")
HEBREW_PATTERN = re.compile(r"[\u0590-\u05FF]")
EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "bank",
    "be",
    "by",
    "central",
    "for",
    "from",
    "has",
    "have",
    "in",
    "inflation",
    "interest",
    "is",
    "market",
    "news",
    "of",
    "on",
    "rate",
    "rates",
    "said",
    "says",
    "stock",
    "that",
    "the",
    "to",
    "was",
    "with",
}
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
class LanguageDetectionResult:
    language: str
    confidence: float
    is_supported_for_full_analysis: bool
    analysis_mode: str


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
    original_language: str
    language_confidence: float
    is_supported_for_full_analysis: bool
    analysis_mode: str
    translation_status: str
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


def strip_boilerplate(text: str) -> str:
    """Remove Telegram promo/footer lines without touching the news body."""

    kept_lines: List[str] = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            kept_lines.append("")
            continue

        compact = WHITESPACE_PATTERN.sub(" ", stripped).strip()
        compact_without_links = TELEGRAM_LINK_PATTERN.sub(" ", compact)
        compact_without_links = URL_PATTERN.sub(" ", compact_without_links)
        compact_without_links = MENTION_PATTERN.sub(" ", compact_without_links)
        compact_without_links = HASHTAG_PATTERN.sub(" ", compact_without_links)
        compact_without_links = EMOJI_PATTERN.sub(" ", compact_without_links)
        compact_without_links = EMOJI_MODIFIER_PATTERN.sub(" ", compact_without_links)
        compact_without_links = PUNCTUATION_PATTERN.sub(" ", compact_without_links)
        remaining_words = compact_without_links.split()

        if LINE_NOISE_PREFIX_PATTERN.search(compact):
            continue
        if TELEGRAM_LINK_PATTERN.search(compact) and len(remaining_words) <= 3:
            continue
        if PROMO_LINE_PATTERN.search(compact):
            continue
        if not remaining_words and (
            URL_PATTERN.search(compact)
            or MENTION_PATTERN.search(compact)
            or HASHTAG_PATTERN.search(compact)
        ):
            continue

        kept_lines.append(line)

    return "\n".join(kept_lines).strip()


def _route_language(
    language: str,
    confidence: float,
    full_analysis_languages: Iterable[str],
) -> LanguageDetectionResult:
    supported = language in set(full_analysis_languages)
    if language == "und":
        mode = "unknown"
    elif supported:
        mode = "full"
    else:
        mode = "partial"
    return LanguageDetectionResult(language, round(confidence, 3), supported, mode)


def _heuristic_detect_raw(text: str, min_confidence: float) -> tuple[str, float]:
    """Unicode-script + EN-stopword heuristic returning raw (lang, confidence).

    Kept public-ish (module-level underscore prefix) so the language_detection
    module can reuse it as its heuristic backend without re-duplicating the
    regex pyramid.
    """

    raw_text = text or ""
    letters = LETTER_PATTERN.findall(raw_text)
    if not letters:
        return "und", 0.0

    total = len(letters)
    cyrillic = len(CYRILLIC_PATTERN.findall(raw_text))
    latin = len(LATIN_PATTERN.findall(raw_text))
    arabic = len(ARABIC_PATTERN.findall(raw_text))
    cjk = len(CJK_PATTERN.findall(raw_text))
    hebrew = len(HEBREW_PATTERN.findall(raw_text))
    script_counts = {
        "ru": cyrillic,
        "latin": latin,
        "ar": arabic,
        "zh": cjk,
        "he": hebrew,
    }
    script, count = max(script_counts.items(), key=lambda item: item[1])
    script_confidence = count / total if total else 0.0

    if script == "ru" and script_confidence >= min_confidence:
        return "ru", script_confidence

    if script == "latin" and script_confidence >= min_confidence:
        words = re.findall(r"[A-Za-z]{2,}", raw_text.lower())
        if not words:
            return "und", round(script_confidence, 3)
        stopword_hits = sum(1 for word in words if word in EN_STOPWORDS)
        english_confidence = max(
            script_confidence * min(1.0, stopword_hits / 2),
            0.5 if stopword_hits else 0.0,
        )
        if english_confidence >= min_confidence:
            return "en", english_confidence
        return "other", script_confidence

    if count > 0 and script_confidence >= min_confidence:
        return script, script_confidence

    return "und", round(script_confidence, 3)


_active_detector = None


def configure_detector(detector) -> None:
    """Install a process-wide language detector used by :func:`detect_language`.

    Called once from the service bootstrap so that the rest of the code path
    (notably :func:`preprocess_text`) doesn't need a detector argument
    threaded through every call site.
    """

    global _active_detector
    _active_detector = detector


def detect_language(
    text: str,
    min_confidence: float = 0.55,
    full_analysis_languages: Iterable[str] = ("ru", "en"),
) -> LanguageDetectionResult:
    detector = _active_detector
    if detector is None:
        lang, conf = _heuristic_detect_raw(text or "", min_confidence)
    else:
        outcome = detector.detect(text or "")
        lang, conf = outcome.language, outcome.confidence
        # fastText can be confident about a short string that's just an emoji
        # or number — trust the raw confidence but downgrade under threshold.
        if conf < min_confidence and lang not in {"und"}:
            return _route_language("und", conf, full_analysis_languages)
    return _route_language(lang, conf, full_analysis_languages)


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
    normalized = normalize_url(url) or url
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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


def preprocess_text(
    text: Optional[str],
    language_min_confidence: float = 0.55,
    full_analysis_languages: Iterable[str] = ("ru", "en"),
) -> PreprocessResult:
    raw_text = text or ""
    content_text = strip_boilerplate(raw_text)
    language = detect_language(
        content_text,
        min_confidence=language_min_confidence,
        full_analysis_languages=full_analysis_languages,
    )
    entity_text = TELEGRAM_LINK_PATTERN.sub(" ", content_text)
    urls = _clean_entities(URL_PATTERN.findall(entity_text))
    mentions = _clean_entities(MENTION_PATTERN.findall(entity_text))
    hashtags = _clean_entities(HASHTAG_PATTERN.findall(entity_text))

    stripped = URL_PATTERN.sub(" ", entity_text)
    stripped = MENTION_PATTERN.sub(" ", stripped)
    stripped = HASHTAG_PATTERN.sub(" ", stripped)
    stripped = EMOJI_PATTERN.sub(" ", stripped)
    stripped = EMOJI_MODIFIER_PATTERN.sub(" ", stripped)
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
        sentences_count=count_sentences(content_text),
        word_count=word_count,
        has_urls=bool(urls),
        has_mentions=bool(mentions),
        has_hashtags=bool(hashtags),
        urls=urls,
        mentions=mentions,
        hashtags=hashtags,
        language=language.language,
        original_language=language.language,
        language_confidence=language.confidence,
        is_supported_for_full_analysis=language.is_supported_for_full_analysis,
        analysis_mode=language.analysis_mode,
        translation_status="not_requested",
        normalized_text_hash=fingerprint_text(stripped),
        simhash64=compute_simhash64(tokens),
        url_fingerprints=url_fingerprints,
        primary_url_fingerprint=primary_url_fingerprint,
    )
