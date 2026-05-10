"""Canonical entity resolver: maps NER surface mentions to entity_canonical rows.

Resolution chain (first match wins):
  1. rule        — entity_normalization_rules
  2. alias_dict  — exact lookup in entity_aliases
  3. fuzzy       — pg_trgm + rapidfuzz (if score >= fuzzy_threshold)
  4. embedding   — stub (if enable_embedding_match)
  5. auto-create — INSERT new entity_canonical if score >= auto_create_threshold

All candidates are written to entity_linking_candidates; the winner has
selected = true.

In-process LRU cache keyed on (alias_normalized, entity_type, language) is
invalidated via LISTEN entity_resolver_invalidate.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from ner_extractor.backends.base import Entity
from ner_extractor.normalization import (
    CanonicalRef,
    Candidate,
    Rule,
    apply_rules,
    embedding_match,
    fuzzy_match,
    lookup_alias,
    surface_normalize,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger("ner_extractor.resolver")


@dataclass
class ResolvedEntity:
    entity: Entity
    canonical_id: Optional[str]
    canonical_name: Optional[str]
    aliases: List[str]
    method: Optional[str]
    score: float


@dataclass
class ResolverConfig:
    enable_canonical_resolution: bool = True
    enable_embedding_match: bool = False
    fuzzy_threshold: float = 0.88
    auto_create_threshold: float = 0.85
    link_threshold: float = 0.70
    cache_size: int = 4096


class CanonicalResolver:
    """Online resolver — runs inside the same asyncpg connection as ner_results INSERT."""

    def __init__(self, config: ResolverConfig, rules: Optional[List[Rule]] = None) -> None:
        self._config = config
        self._rules: List[Rule] = rules or []
        # (alias_normalized, entity_type, language) -> canonical_id | None
        self._cache: Dict[Tuple[str, str, str], Optional[str]] = {}
        self._cache_max = config.cache_size

    # ── rule management ──────────────────────────────────────────────────────

    def update_rules(self, rules: List[Rule]) -> None:
        self._rules = rules
        self._cache.clear()

    def invalidate_cache(self) -> None:
        self._cache.clear()

    # ── resolution ───────────────────────────────────────────────────────────

    async def resolve(
        self,
        conn: "asyncpg.Connection",
        entity: Entity,
        ner_result_id: str,
        language: str,
    ) -> ResolvedEntity:
        if not self._config.enable_canonical_resolution:
            return ResolvedEntity(entity=entity, canonical_id=None, canonical_name=None, aliases=[], method=None, score=0.0)

        alias_norm = surface_normalize(entity.normalized or entity.text, language)
        cache_key = (alias_norm, entity.entity_type, language)

        if cache_key in self._cache:
            cached_id = self._cache[cache_key]
            if cached_id:
                name = await self._fetch_canonical_name(conn, cached_id)
                aliases = await self._fetch_aliases(conn, cached_id)
                return ResolvedEntity(entity=entity, canonical_id=cached_id, canonical_name=name, aliases=aliases, method="cache", score=1.0)

        candidates: List[Candidate] = []
        winner: Optional[Candidate] = None

        # 1. rule
        rule_hit = apply_rules(alias_norm, entity.entity_type, language, self._rules)
        if rule_hit:
            winner = Candidate(canonical_id=rule_hit.target_canonical_id, canonical_name="", method="rule", score=1.0)

        # 2. alias_dict
        if not winner:
            ref = await lookup_alias(alias_norm, entity.entity_type, language, conn)
            if ref:
                winner = Candidate(canonical_id=ref.canonical_id, canonical_name="", method="alias_dict", score=1.0)

        # 3. fuzzy
        if not winner:
            fuzzy_candidates = await fuzzy_match(
                alias_norm, entity.entity_type, language, conn, self._config.fuzzy_threshold
            )
            candidates.extend(fuzzy_candidates)
            if fuzzy_candidates and fuzzy_candidates[0].score >= self._config.fuzzy_threshold:
                winner = fuzzy_candidates[0]

        # 4. embedding (stub)
        if not winner and self._config.enable_embedding_match:
            emb_candidates = await embedding_match(alias_norm, entity.entity_type, language, None, conn)
            candidates.extend(emb_candidates)
            if emb_candidates and emb_candidates[0].score >= self._config.link_threshold:
                winner = emb_candidates[0]

        # 5. auto-create
        if not winner:
            top_score = candidates[0].score if candidates else 0.0
            if top_score >= self._config.auto_create_threshold:
                winner = candidates[0]
            else:
                # create new canonical
                canonical_id = await self._upsert_canonical(conn, entity, alias_norm, language)
                winner = Candidate(canonical_id=canonical_id, canonical_name=entity.normalized or entity.text, method="auto", score=1.0)

        # write linking candidates
        await self._write_candidates(conn, ner_result_id, [winner] + [c for c in candidates if c.canonical_id != winner.canonical_id], winner.canonical_id)

        # ensure alias exists for winner
        await self._ensure_alias(conn, winner.canonical_id, alias_norm, entity, language, winner.method)

        # bump mention count & last_seen_at
        await conn.execute(
            "UPDATE entity_canonical SET mention_count = mention_count + 1, last_seen_at = NOW() WHERE id = $1",
            uuid.UUID(winner.canonical_id),
        )

        canonical_name = await self._fetch_canonical_name(conn, winner.canonical_id)
        aliases = await self._fetch_aliases(conn, winner.canonical_id)

        # update cache
        if len(self._cache) >= self._cache_max:
            # evict oldest (simple FIFO approximation)
            try:
                self._cache.pop(next(iter(self._cache)))
            except StopIteration:
                pass
        self._cache[cache_key] = winner.canonical_id

        return ResolvedEntity(
            entity=entity,
            canonical_id=winner.canonical_id,
            canonical_name=canonical_name,
            aliases=aliases,
            method=winner.method,
            score=winner.score,
        )

    async def resolve_many(
        self,
        conn: "asyncpg.Connection",
        entities: List[Entity],
        ner_result_ids: List[str],
        language: str,
    ) -> List[ResolvedEntity]:
        return [
            await self.resolve(conn, ent, rid, language)
            for ent, rid in zip(entities, ner_result_ids)
        ]

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _upsert_canonical(
        self,
        conn: "asyncpg.Connection",
        entity: Entity,
        name_normalized: str,
        language: str,
    ) -> str:
        canonical_name = entity.normalized or entity.text
        row = await conn.fetchrow(
            """
            INSERT INTO entity_canonical
                (canonical_name, canonical_name_normalized, entity_type, language,
                 confidence, source_model, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
            ON CONFLICT (canonical_name_normalized, entity_type)
            WHERE merged_into_id IS NULL
            DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                mention_count = entity_canonical.mention_count + 1
            RETURNING id
            """,
            canonical_name,
            name_normalized,
            entity.entity_type,
            language or None,
            float(entity.confidence),
            None,
        )
        return str(row["id"])

    async def _ensure_alias(
        self,
        conn: "asyncpg.Connection",
        canonical_id: str,
        alias_norm: str,
        entity: Entity,
        language: str,
        source: str,
    ) -> None:
        # Map internal method names to allowed source values
        src = source if source in ("rule", "dictionary", "fuzzy", "embedding", "manual", "model") else "model"
        await conn.execute(
            """
            INSERT INTO entity_aliases
                (entity_canonical_id, alias, alias_normalized, language, source, confidence)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (entity_canonical_id, alias_normalized) DO NOTHING
            """,
            uuid.UUID(canonical_id),
            entity.text,
            alias_norm,
            language or None,
            src,
            float(entity.confidence),
        )

    async def _write_candidates(
        self,
        conn: "asyncpg.Connection",
        ner_result_id: str,
        candidates: List[Candidate],
        winning_id: str,
    ) -> None:
        for c in candidates:
            if not c.canonical_id:
                continue
            method = c.method if c.method in ("exact", "rule", "alias_dict", "fuzzy", "embedding", "llm") else "exact"
            await conn.execute(
                """
                INSERT INTO entity_linking_candidates
                    (ner_result_id, entity_canonical_id, score, method, selected)
                VALUES ($1, $2, $3, $4, $5)
                """,
                uuid.UUID(ner_result_id),
                uuid.UUID(c.canonical_id),
                float(c.score),
                method,
                c.canonical_id == winning_id,
            )

    async def _fetch_canonical_name(self, conn: "asyncpg.Connection", canonical_id: str) -> Optional[str]:
        row = await conn.fetchrow(
            "SELECT canonical_name FROM entity_canonical WHERE id = $1", uuid.UUID(canonical_id)
        )
        return row["canonical_name"] if row else None

    async def _fetch_aliases(self, conn: "asyncpg.Connection", canonical_id: str) -> List[str]:
        rows = await conn.fetch(
            "SELECT alias FROM entity_aliases WHERE entity_canonical_id = $1 ORDER BY is_primary DESC, confidence DESC LIMIT 10",
            uuid.UUID(canonical_id),
        )
        return [r["alias"] for r in rows]


async def load_rules_from_db(conn: "asyncpg.Connection") -> List[Rule]:
    """Fetch all enabled normalization rules ordered by priority DESC."""
    rows = await conn.fetch(
        """
        SELECT id, rule_type, pattern, replacement, entity_type, language,
               target_canonical_id, priority
        FROM entity_normalization_rules
        WHERE enabled = true
        ORDER BY priority DESC
        """
    )
    return [
        Rule(
            id=str(r["id"]),
            rule_type=r["rule_type"],
            pattern=r["pattern"],
            replacement=r["replacement"],
            entity_type=r["entity_type"],
            language=r["language"],
            target_canonical_id=str(r["target_canonical_id"]) if r["target_canonical_id"] else None,
            priority=r["priority"],
        )
        for r in rows
    ]
