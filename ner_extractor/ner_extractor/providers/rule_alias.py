"""Rule-based alias post-pass using Aho-Corasick substring search.

Finds entity mentions that the neural backends may have missed by scanning for
known alias strings from entity_aliases + entity_normalization_rules tables.
The alias automaton is built once on startup and invalidated via
LISTEN entity_resolver_invalidate.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional, Tuple

from ner_extractor.backends.base import Entity
from ner_extractor.normalization import surface_normalize
from ner_extractor.providers.base import NerProvider

logger = logging.getLogger("ner_extractor.providers.rule_alias")

# (alias_normalized, entity_type, language) -> canonical_id
_AliasKey = Tuple[str, str, Optional[str]]


class RuleBasedAliasProvider(NerProvider):
    """Post-pass provider: adds entities for known aliases not found by models.

    Operates only when the alias cache has been populated (call load_aliases()).
    Missing canonical entries are silently skipped — this provider never raises.
    """

    name = "rule_alias"
    version = "1.0.0"
    provider_kind = "rule"

    def __init__(self, language: str = "") -> None:
        self.language = language
        self._lock = threading.RLock()
        # alias_normalized -> (entity_type, canonical_id, original_alias)
        self._alias_map: Dict[str, Tuple[str, str, str]] = {}
        self._automaton = None  # ahocorasick.Automaton once available

    # ── public API ──────────────────────────────────────────────────────────

    def load_aliases(self, rows: List[Tuple[str, str, str, Optional[str]]]) -> None:
        """Rebuild automaton from (alias_normalized, entity_type, canonical_id, language)."""
        try:
            import ahocorasick
        except ImportError:
            logger.warning("ahocorasick not installed; RuleBasedAliasProvider disabled")
            return

        with self._lock:
            A = ahocorasick.Automaton()
            new_map: Dict[str, Tuple[str, str, str]] = {}
            for alias_norm, entity_type, canonical_id, lang in rows:
                if lang and lang != self.language:
                    continue
                new_map[alias_norm] = (entity_type, canonical_id, alias_norm)
                A.add_word(alias_norm, (alias_norm, entity_type, canonical_id))
            A.make_automaton()
            self._alias_map = new_map
            self._automaton = A
        logger.info("RuleBasedAliasProvider loaded %d aliases", len(self._alias_map))

    def invalidate(self) -> None:
        """Clear alias cache (triggers reload on next load_aliases call)."""
        with self._lock:
            self._alias_map = {}
            self._automaton = None

    def extract(self, text: str) -> List[Entity]:
        """Find alias matches in text, return as Entity list (no span dedup with model output)."""
        with self._lock:
            automaton = self._automaton

        if automaton is None or not text:
            return []

        norm_text = surface_normalize(text, self.language)
        entities: List[Entity] = []

        try:
            for end_idx, (alias_norm, entity_type, canonical_id) in automaton.iter(norm_text):
                start_idx = end_idx - len(alias_norm) + 1
                # map normalised offsets back to original text approximately
                surface = text[start_idx:start_idx + len(alias_norm)]
                entities.append(
                    Entity(
                        text=surface,
                        entity_type=entity_type,
                        start=start_idx,
                        end=start_idx + len(alias_norm),
                        confidence=0.95,
                        normalized=alias_norm,
                    )
                )
        except Exception:  # noqa: BLE001
            logger.exception("RuleBasedAliasProvider.extract failed")
        return entities
