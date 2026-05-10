from __future__ import annotations

import re
from typing import Optional

_ARXIV_RE = re.compile(r"arxiv\.org/(abs|pdf)/[\d\.]+", re.I)
_OPENREVIEW_RE = re.compile(r"openreview\.net", re.I)
_DOI_RE = re.compile(r"doi\.org/10\.", re.I)
_PDF_RE = re.compile(r"https?://[^\s]+\.pdf(\?[^\s]*)?$", re.I)

_KEYWORDS = frozenset({
    "arxiv", "preprint", "paper", "benchmark", "dataset",
    "sota", "model", "method", "neural", "transformer",
})


def detect(message: dict) -> tuple[bool, str, Optional[str]]:
    """Returns (is_paper, source_type, source_url)."""
    urls: list[str] = message.get("urls") or []
    media: dict = message.get("media") or {}
    text: str = (
        message.get("cleaned_text") or message.get("text") or ""
    ).lower()

    for url in urls:
        if _ARXIV_RE.search(url):
            return True, "arxiv", url
        if _OPENREVIEW_RE.search(url):
            return True, "openreview", url
        if _DOI_RE.search(url):
            return True, "doi", url
        if _PDF_RE.match(url):
            return True, "pdf_url", url

    if (
        media.get("type") == "document"
        and media.get("mime_type") == "application/pdf"
    ):
        return True, "telegram_file", None

    if any(kw in text for kw in _KEYWORDS):
        return True, "webpage", None

    return False, "", None
