from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

import httpx

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass
class ArxivMetadata:
    arxiv_id: str
    title: Optional[str]
    authors: list[str]
    abstract: Optional[str]
    published_at: Optional[str]
    pdf_url: Optional[str]


async def fetch_arxiv_metadata(url: str, timeout: int = 30) -> Optional[ArxivMetadata]:
    m = _ARXIV_ID_RE.search(url)
    if not m:
        return None
    arxiv_id = m.group(1)

    api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(api_url)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    entry = root.find("atom:entry", _NS)
    if entry is None:
        return None

    title_el = entry.find("atom:title", _NS)
    title = title_el.text.strip().replace("\n", " ") if title_el is not None else None

    authors = []
    for author_el in entry.findall("atom:author", _NS):
        name_el = author_el.find("atom:name", _NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    summary_el = entry.find("atom:summary", _NS)
    abstract = summary_el.text.strip().replace("\n", " ") if summary_el is not None else None

    published_el = entry.find("atom:published", _NS)
    published_at = published_el.text if published_el is not None else None

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

    return ArxivMetadata(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        published_at=published_at,
        pdf_url=pdf_url,
    )
