from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from paper_summarizer.config import MistralConfig

logger = logging.getLogger("paper_summarizer.mistral")


class MistralClient:
    def __init__(self, config: MistralConfig) -> None:
        self._config = config

    async def complete(self, prompt: str) -> str:
        """Call Mistral chat completion, return raw text response."""
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        last_exc: Optional[Exception] = None
        for attempt in range(self._config.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
                    resp = await client.post(
                        f"{self._config.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except Exception as exc:
                logger.warning("Mistral attempt %d failed: %s", attempt + 1, exc)
                last_exc = exc
        raise RuntimeError(f"Mistral failed after {self._config.max_retries} attempts") from last_exc


class MockMistralClient:
    """For testing."""
    def __init__(self, response: str) -> None:
        self._response = response

    async def complete(self, prompt: str) -> str:
        return self._response
