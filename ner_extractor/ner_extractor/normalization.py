"""Surface normalization and rule-based alias matching for canonical entity resolution."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    import asyncpg


@dataclass
class Rule:
    id: str
    rule_type: str  # alias | abbreviation | regex | merge
    pattern: str
    replacement: Optional[str]
    entity_type: Optional[str]
    language: Optional[str]
    target_canonical_id: Optional[str]
    priority: int


@dataclass
class RuleHit:
    target_canonical_id: str
    method: str  # rule | alias_dict
    score: float


@dataclass
class CanonicalRef:
    canonical_id: str
    method: str
    score: float


@dataclass
class Candidate:
    canonical_id: str
    canonical_name: str
    method: str
    score: float


# ─── surface normalisation ────────────────────────────────────────────────────

def surface_normalize(text: str, language: str = "") -> str:
    """NFKC + casefold + strip quotes/brackets/extra whitespace."""
    text = unicodedata.normalize("NFKC", text)
    # remove quotation marks (including «»)
    text = re.sub(r'[«»""\'`´]', "", text)
    # remove surrounding brackets
    text = re.sub(r"[\(\)\[\]{}]", "", text)
    # normalise dashes
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    text = re.sub(r"\s*-\s*", "-", text)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # punctuation trim at edges
    text = text.strip(".,;:!?")
    return text.casefold()


# ─── rule application ─────────────────────────────────────────────────────────

def apply_rules(
    text: str,
    entity_type: str,
    language: str,
    rules: List[Rule],
) -> Optional[RuleHit]:
    """Iterate rules sorted by priority DESC; return first hit or None."""
    norm = surface_normalize(text, language)
    for rule in sorted(rules, key=lambda r: r.priority, reverse=True):
        if not rule.target_canonical_id:
            continue
        if rule.entity_type and rule.entity_type != entity_type:
            continue
        if rule.language and rule.language != language:
            continue

        if rule.rule_type == "regex":
            if re.fullmatch(rule.pattern, norm):
                return RuleHit(rule.target_canonical_id, "rule", 1.0)
        elif rule.rule_type in ("alias", "abbreviation"):
            if surface_normalize(rule.pattern) == norm:
                return RuleHit(rule.target_canonical_id, "rule", 1.0)
    return None


# ─── alias dict lookup ────────────────────────────────────────────────────────

async def lookup_alias(
    alias_normalized: str,
    entity_type: str,
    language: str,
    conn: "asyncpg.Connection",
) -> Optional[CanonicalRef]:
    """Exact lookup in entity_aliases."""
    row = await conn.fetchrow(
        """
        SELECT ea.entity_canonical_id
        FROM entity_aliases ea
        JOIN entity_canonical ec ON ec.id = ea.entity_canonical_id
        WHERE ea.alias_normalized = $1
          AND ($2::text IS NULL OR ec.entity_type = $2)
          AND ($3::text IS NULL OR ea.language IS NULL OR ea.language = $3)
          AND ec.merged_into_id IS NULL
        ORDER BY ea.is_primary DESC, ea.confidence DESC
        LIMIT 1
        """,
        alias_normalized, entity_type or None, language or None,
    )
    if row:
        return CanonicalRef(str(row["entity_canonical_id"]), "alias_dict", 1.0)
    return None


# ─── fuzzy matching ───────────────────────────────────────────────────────────

async def fuzzy_match(
    query_norm: str,
    entity_type: str,
    language: str,
    conn: "asyncpg.Connection",
    threshold: float = 0.88,
) -> List[Candidate]:
    """
    Two-stage: pg_trgm pre-filter → rapidfuzz re-rank.
    For Russian, lemmatise the query via pymorphy2 before fuzzy comparison.
    """
    from rapidfuzz import fuzz

    # optional pymorphy2 lemmatisation for Russian queries
    lemmatised = _lemmatise_ru(query_norm) if language == "ru" else query_norm

    rows = await conn.fetch(
        """
        SELECT ec.id, ec.canonical_name_normalized,
               similarity(ea.alias_normalized, $1) AS trgm_score
        FROM entity_aliases ea
        JOIN entity_canonical ec ON ec.id = ea.entity_canonical_id
        WHERE ($2::text IS NULL OR ec.entity_type = $2)
          AND ec.merged_into_id IS NULL
          AND similarity(ea.alias_normalized, $1) > 0.5
        UNION
        SELECT ec.id, ec.canonical_name_normalized,
               similarity(ec.canonical_name_normalized, $1) AS trgm_score
        FROM entity_canonical ec
        WHERE ($2::text IS NULL OR ec.entity_type = $2)
          AND ec.merged_into_id IS NULL
          AND similarity(ec.canonical_name_normalized, $1) > 0.5
        ORDER BY trgm_score DESC
        LIMIT 20
        """,
        lemmatised, entity_type or None,
    )

    candidates: List[Candidate] = []
    for row in rows:
        target = row["canonical_name_normalized"]
        score = max(
            fuzz.token_set_ratio(lemmatised, target) / 100.0,
            fuzz.partial_ratio(lemmatised, target) / 100.0,
        )
        if score >= threshold:
            candidates.append(
                Candidate(
                    canonical_id=str(row["id"]),
                    canonical_name=row["canonical_name_normalized"],
                    method="fuzzy",
                    score=score,
                )
            )
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


# ─── embedding matching (stub) ────────────────────────────────────────────────

async def embedding_match(
    query: str,
    entity_type: str,
    language: str,
    embedder: object,
    conn: "asyncpg.Connection",
    top_k: int = 10,
) -> List[Candidate]:
    """Stub — full implementation is a follow-up task."""
    return []


# ─── internal helpers ─────────────────────────────────────────────────────────

def _lemmatise_ru(text: str) -> str:
    """Lemmatise Russian tokens via pymorphy2 (best parse, normal_form)."""
    try:
        import pymorphy2  # already a dependency via natasha backend
        morph = _get_morph()
        tokens = text.split()
        lemmas = []
        for tok in tokens:
            if re.search(r"[А-Яа-яЁё]", tok):
                lemmas.append(morph.parse(tok)[0].normal_form)
            else:
                lemmas.append(tok)
        return " ".join(lemmas)
    except ImportError:
        return text


_morph_instance = None


def _get_morph():
    global _morph_instance
    if _morph_instance is None:
        import pymorphy2
        _morph_instance = pymorphy2.MorphAnalyzer()
    return _morph_instance
