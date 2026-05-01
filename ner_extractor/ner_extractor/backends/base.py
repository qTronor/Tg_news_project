"""Shared types and protocol for NER backends."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol


# Union of entity types emitted across all backends. dslim emits PER/LOC/ORG/MISC;
# Natasha emits PER/LOC/ORG (mapped to PERSON/LOC/ORG). MISC is accepted from EN.
CANONICAL_ENTITY_TYPES = frozenset({"PERSON", "ORG", "LOC", "MISC"})


@dataclass
class Entity:
    """Unified entity representation shared across Natasha and transformers backends."""

    text: str           # original span text
    entity_type: str    # one of CANONICAL_ENTITY_TYPES
    start: int          # character offset in the input text
    end: int            # character offset (exclusive)
    confidence: float
    normalized: Optional[str] = None


class NerBackend(Protocol):
    """Language-specific NER backend.

    Implementations guarantee:
    * ``name`` / ``version`` / ``language`` are stable.
    * ``extract`` returns entities in document order; deduplication within a
      single call is handled by the backend.
    * Empty / whitespace-only text returns an empty list, never raises.
    """

    name: str
    version: str
    language: str

    def extract(self, text: str) -> List[Entity]:
        ...
