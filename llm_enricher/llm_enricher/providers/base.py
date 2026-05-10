from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    tokens_input: int
    tokens_output: int
    raw_text: str


class ProviderError(Exception):
    """Base class for provider errors."""


class ProviderTransientError(ProviderError):
    """Retriable: network issues, 5xx, 429."""


class ProviderInvalidOutputError(ProviderError):
    """Non-retriable: response doesn't match expected JSON schema."""


class ProviderUnsupportedError(ProviderError):
    """Non-retriable: provider can't handle this request."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model_name: str

    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        max_tokens: int,
        temperature: float = 0.2,
    ) -> LLMResult: ...
