from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import asyncpg

from llm_enricher import fingerprint as fp
from llm_enricher.config import CacheConfig
from llm_enricher.repository import ClusterContextRepository
from llm_enricher.schemas import ClusterEnrichmentInput

logger = logging.getLogger("llm_enricher.cache")

_INSERT_SQL = """
INSERT INTO llm_enrichments (
    cache_key, public_cluster_id, enrichment_type, language, analysis_mode,
    prompt_version, model_provider, model_name, input_fingerprint,
    result_json, tokens_input, tokens_output, cost_usd, latency_ms,
    status, error_message, expires_at
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, $12, $13, $14,
    $15, $16, $17
)
ON CONFLICT (cache_key) DO UPDATE SET
    result_json     = EXCLUDED.result_json,
    tokens_input    = EXCLUDED.tokens_input,
    tokens_output   = EXCLUDED.tokens_output,
    cost_usd        = EXCLUDED.cost_usd,
    latency_ms      = EXCLUDED.latency_ms,
    status          = EXCLUDED.status,
    error_message   = EXCLUDED.error_message,
    created_at      = NOW(),
    expires_at      = EXCLUDED.expires_at;
"""

_SELECT_SQL = """
SELECT result_json, status, error_message, tokens_input, tokens_output,
       cost_usd, latency_ms, prompt_version, model_provider, model_name,
       language, analysis_mode, created_at
FROM llm_enrichments
WHERE cache_key = $1 AND expires_at > NOW();
"""


@dataclass
class ComputedResult:
    result_json: Optional[dict[str, Any]]
    status: str
    error_message: Optional[str]
    tokens_input: int
    tokens_output: int
    cost_usd: float
    latency_ms: int
    prompt_version: str
    model_provider: str
    model_name: str
    language: str
    analysis_mode: str


@dataclass
class CacheLookupResult:
    dto: ClusterEnrichmentInput
    computed: ComputedResult
    cached: bool
    input_fingerprint: str
    used_cache_key: str


class EnrichmentCache:
    def __init__(
        self,
        pool: asyncpg.Pool,
        repo: ClusterContextRepository,
        config: CacheConfig,
    ) -> None:
        self._pool = pool
        self._repo = repo
        self._config = config

    async def get_or_compute(
        self,
        public_cluster_id: str,
        enrichment_type: str,
        *,
        refresh: bool,
        compute: Callable[[ClusterEnrichmentInput], Awaitable[ComputedResult]],
        prompt_version: str,
        model_name: str,
    ) -> CacheLookupResult:
        dto = await self._repo.fetch(public_cluster_id)
        fingerprint = fp.input_fingerprint(dto.model_dump(mode="json"))
        key = fp.cache_key(
            public_cluster_id,
            enrichment_type,
            dto.language,
            prompt_version,
            model_name,
            fingerprint,
        )

        if not refresh:
            cached_row = await self._lookup(key)
            if cached_row is not None:
                logger.debug("Cache hit for key=%s", key[:16])
                return CacheLookupResult(
                    dto=dto,
                    computed=cached_row,
                    cached=True,
                    input_fingerprint=fingerprint,
                    used_cache_key=key,
                )

        computed = await compute(dto)
        await self._store(key, public_cluster_id, enrichment_type, dto, computed, fingerprint)
        return CacheLookupResult(
            dto=dto,
            computed=computed,
            cached=False,
            input_fingerprint=fingerprint,
            used_cache_key=key,
        )

    async def _lookup(self, key: str) -> Optional[ComputedResult]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_SELECT_SQL, key)
        if row is None:
            return None
        raw_result = row["result_json"]
        result_json = (
            json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        )
        return ComputedResult(
            result_json=result_json,
            status=row["status"],
            error_message=row["error_message"],
            tokens_input=row["tokens_input"] or 0,
            tokens_output=row["tokens_output"] or 0,
            cost_usd=float(row["cost_usd"] or 0),
            latency_ms=row["latency_ms"] or 0,
            prompt_version=row["prompt_version"],
            model_provider=row["model_provider"],
            model_name=row["model_name"],
            language=row["language"],
            analysis_mode=row["analysis_mode"],
        )

    async def _store(
        self,
        key: str,
        public_cluster_id: str,
        enrichment_type: str,
        dto: ClusterEnrichmentInput,
        computed: ComputedResult,
        fingerprint: str,
    ) -> None:
        ttl = (
            self._config.error_ttl_seconds
            if computed.status == "error"
            else self._config.ttl_seconds
        )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        result_json_str = (
            json.dumps(computed.result_json, ensure_ascii=False)
            if computed.result_json is not None
            else None
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL,
                key,
                public_cluster_id,
                enrichment_type,
                dto.language,
                dto.analysis_mode,
                computed.prompt_version,
                computed.model_provider,
                computed.model_name,
                fingerprint,
                result_json_str,
                computed.tokens_input,
                computed.tokens_output,
                computed.cost_usd,
                computed.latency_ms,
                computed.status,
                computed.error_message,
                expires_at,
            )
        logger.debug("Stored enrichment cache key=%s status=%s", key[:16], computed.status)
