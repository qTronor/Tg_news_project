"""Natasha-based Russian NER backend.

Wraps the Natasha + pymorphy2 extraction logic that previously lived inline
in ``service.py``. Provides lemmatized / title-cased canonical forms for
PER/ORG/LOC entities.
"""
from __future__ import annotations

import re
from typing import List, Optional, Set, Tuple

from ner_extractor.backends.base import Entity


# Natasha type → canonical pipeline type
_TYPE_MAP = {"PER": "PERSON", "ORG": "ORG", "LOC": "LOC"}


class NatashaRuBackend:
    """Natasha NER + pymorphy2 normalisation for Russian text."""

    name = "natasha"
    language = "ru"

    def __init__(self, *, version: str = "1.0.0", min_entity_length: int = 3) -> None:
        self.version = version
        self._min_entity_length = min_entity_length

        # Eager load at construction time so the first real message doesn't pay
        # the 1-2 second Natasha init cost inside a request path.
        import pymorphy2
        from natasha import NewsEmbedding, NewsNERTagger, Segmenter

        self._segmenter = Segmenter()
        emb = NewsEmbedding()
        self._ner_tagger = NewsNERTagger(emb)
        self._morph = pymorphy2.MorphAnalyzer()

    # ── public API ──────────────────────────────────────────────────────────

    def extract(self, text: str) -> List[Entity]:
        if not text or not text.strip():
            return []

        from natasha import Doc

        doc = Doc(text)
        doc.segment(self._segmenter)
        doc.tag_ner(self._ner_tagger)

        entities: List[Entity] = []
        seen: Set[Tuple[str, int, int]] = set()
        for span in doc.spans:
            if span.type not in _TYPE_MAP:
                continue
            normalized_text = self._normalize_surface(span.text)
            if len(normalized_text) < self._min_entity_length:
                continue
            if normalized_text.isnumeric():
                continue
            dedup_key = (normalized_text.lower(), span.start, span.stop)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            canonical = self._canonicalize(normalized_text, span.type)
            entities.append(
                Entity(
                    text=span.text,
                    entity_type=_TYPE_MAP[span.type],
                    start=span.start,
                    end=span.stop,
                    confidence=1.0,
                    normalized=canonical,
                )
            )
        return entities

    # ── normalisation helpers ────────────────────────────────────────────────

    def _normalize_surface(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"[\"'«»]", "", text)
        text = re.sub(r"[\(\)\[\]{}]", "", text)
        text = re.sub(r"[‐‑‒–—−]", "-", text)
        text = re.sub(r"\s*-\s*", "-", text)
        if text.isupper():
            text = text.title()
        return text.strip()

    def _canonicalize(self, text: str, natasha_type: str) -> str:
        if natasha_type == "PER":
            return self._canonicalize_person(text)
        tokens = text.split()
        lemmas = []
        for tok in tokens:
            if not re.search(r"[A-Za-zА-Яа-яЁё]", tok):
                continue
            if tok.isupper() and len(tok) <= 5:
                lemmas.append(tok)
            else:
                parsed = self._morph.parse(tok)
                lemmas.append(parsed[0].normal_form)
        if not lemmas:
            return text
        return " ".join(w if w.isupper() else w.title() for w in lemmas)

    def _canonicalize_person(self, text: str) -> str:
        tokens = text.split()
        tokens = [t for t in tokens if re.search(r"[A-Za-zА-Яа-яЁё]", t)]
        if not tokens:
            return text
        parsed_tokens = []
        for tok in tokens:
            parses = self._morph.parse(tok)
            best = parses[0]
            role = None
            lemma = best.normal_form
            for p in parses:
                if "Surn" in p.tag:
                    role = "Surn"
                    lemma = p.normal_form
                    break
                if "Name" in p.tag and role is None:
                    role = "Name"
                    lemma = p.normal_form
                if "Patr" in p.tag and role is None:
                    role = "Patr"
                    lemma = p.normal_form
            parsed_tokens.append({"lemma": lemma, "role": role})
        surname = next(
            (p["lemma"] for p in parsed_tokens if p["role"] == "Surn"), None
        )
        name = next(
            (p["lemma"] for p in parsed_tokens if p["role"] == "Name"), None
        )
        patronymic = next(
            (p["lemma"] for p in parsed_tokens if p["role"] == "Patr"), None
        )
        if surname or name:
            ordered = [w for w in [surname, name, patronymic] if w]
            return " ".join(w.title() for w in ordered)
        return " ".join(p["lemma"].title() for p in parsed_tokens)
