from __future__ import annotations

import io
from typing import Optional

import httpx
import fitz  # PyMuPDF


async def download_and_extract_text(
    url: str, timeout: int = 30
) -> Optional[str]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if "pdf" not in resp.headers.get("content-type", "").lower() and not url.lower().endswith(".pdf"):
            return None
        pdf_bytes = resp.content

    return extract_text_from_bytes(pdf_bytes)


def extract_text_from_bytes(pdf_bytes: bytes) -> Optional[str]:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n".join(pages)
    except Exception:
        return None
