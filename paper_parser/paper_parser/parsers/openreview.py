from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import httpx

_FORUM_RE = re.compile(r"id=([A-Za-z0-9_-]+)")


@dataclass
class OpenReviewMetadata:
    title: Optional[str]
    authors: list[str]
    abstract: Optional[str]
    pdf_url: Optional[str]


async def fetch_openreview_metadata(url: str, timeout: int = 30) -> Optional[OpenReviewMetadata]:
    m = _FORUM_RE.search(url)
    if not m:
        return None
    paper_id = m.group(1)

    api_url = f"https://api2.openreview.net/notes?forum={paper_id}&details=replyCount"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(api_url, headers={"User-Agent": "paper-parser/1.0"})
        if resp.status_code != 200:
            return None
        data = resp.json()

    notes = data.get("notes") or []
    if not notes:
        return None
    note = notes[0]
    content = note.get("content") or {}

    title = _get_value(content.get("title"))
    authors_raw = content.get("authors", {})
    authors = _get_list(authors_raw)
    abstract = _get_value(content.get("abstract"))
    pdf_url = f"https://openreview.net/pdf?id={paper_id}"

    return OpenReviewMetadata(
        title=title, authors=authors, abstract=abstract, pdf_url=pdf_url
    )


def _get_value(field) -> Optional[str]:
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("value")
    return str(field)


def _get_list(field) -> list[str]:
    if field is None:
        return []
    if isinstance(field, dict):
        val = field.get("value", [])
        return val if isinstance(val, list) else []
    if isinstance(field, list):
        return field
    return []
