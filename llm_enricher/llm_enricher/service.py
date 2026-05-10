from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import asyncpg
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from llm_enricher import fingerprint as fp
from llm_enricher.budget import DailyBudgetTracker
from llm_enricher.cache import EnrichmentCache
from llm_enricher.config import AppConfig
from llm_enricher.handlers import EnrichmentHandler, build_handlers
from llm_enricher.metrics import ENRICH_CACHE_HITS, ENRICH_LATENCY, ENRICH_REQUESTS
from llm_enricher.providers.base import LLMProvider
from llm_enricher.providers.mistral import MistralProvider
from llm_enricher.providers.mock import MockProvider
from llm_enricher.repository import ClusterContextRepository
from llm_enricher.schemas import SUPPORTED_ENRICHMENT_TYPES

# Maps summary "kind" names (public API) → enrichment_type (internal)
_KIND_TO_ENRICHMENT_TYPE: dict[str, str] = {
    "short": "cluster_summary",
    "timeline": "timeline_summary",
    "key_actors": "key_actors_summary",
    "why_important": "cluster_explanation",
    "what_changed": "what_changed_recently",
    "novelty": "novelty_explanation",
}
_ALL_KINDS = list(_KIND_TO_ENRICHMENT_TYPE.keys())

logger = logging.getLogger("llm_enricher")


@dataclass
class HealthState:
    ready: bool = False
    postgres_connected: bool = False
    last_processed_at: Optional[str] = None
    last_error: Optional[str] = None


def _build_provider(config: AppConfig) -> LLMProvider:
    if config.llm.provider == "mistral":
        return MistralProvider(
            model_name=config.llm.model_name,
            timeout_seconds=config.llm.timeout_seconds,
            retry_attempts=config.llm.retry_attempts,
            circuit_breaker_fail_max=config.llm.circuit_breaker.fail_max,
            circuit_breaker_reset_timeout=config.llm.circuit_breaker.reset_timeout_seconds,
        )
    return MockProvider()


class LLMEnricherService:
    def __init__(self, config: AppConfig, prompts_root: Optional[Path] = None) -> None:
        self._config = config
        self._prompts_root = prompts_root
        self._pool: Optional[asyncpg.Pool] = None
        self._health = HealthState()
        self._web_runner: Optional[web.AppRunner] = None

    async def start(self) -> None:
        await self._start_db()
        await self._start_http()

        provider = _build_provider(self._config)

        self._budget = DailyBudgetTracker(self._config.budget)
        assert self._pool is not None
        await self._budget.warm_start(self._pool)

        repo = ClusterContextRepository(self._pool)
        self._cache = EnrichmentCache(self._pool, repo, self._config.cache)
        self._handlers = build_handlers(provider, self._budget, self._config, self._prompts_root)

        self._health.ready = True
        logger.info("llm_enricher started, provider=%s", self._config.llm.provider)

    async def stop(self) -> None:
        self._health.ready = False
        if self._pool is not None:
            await self._pool.close()
        if self._web_runner is not None:
            await self._web_runner.cleanup()
        logger.info("llm_enricher stopped")

    # ── DB ────────────────────────────────────────────────────────────

    async def _start_db(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn(),
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
        self._health.postgres_connected = True

    # ── HTTP ──────────────────────────────────────────────────────────

    async def _start_http(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/ready", self._handle_ready)
        app.router.add_get("/metrics", self._handle_metrics)
        app.router.add_post("/enrich/{enrichment_type}", self._handle_enrich)
        app.router.add_post("/summary/{public_cluster_id}", self._handle_summary)

        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()

        health_site = web.TCPSite(
            self._web_runner,
            self._config.health.host,
            self._config.health.port,
        )
        await health_site.start()

        if (self._config.metrics.host, self._config.metrics.port) != (
            self._config.health.host,
            self._config.health.port,
        ):
            metrics_site = web.TCPSite(
                self._web_runner,
                self._config.metrics.host,
                self._config.metrics.port,
            )
            await metrics_site.start()

    # ── Handlers ──────────────────────────────────────────────────────

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok" if self._health.ready else "starting",
            "ready": self._health.ready,
            "postgres_connected": self._health.postgres_connected,
            "last_processed_at": self._health.last_processed_at,
            "last_error": self._health.last_error,
        })

    async def _handle_ready(self, request: web.Request) -> web.Response:
        if self._health.ready:
            return web.Response(text="ok")
        return web.Response(status=503, text="not ready")

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        return web.Response(
            body=generate_latest(),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    async def _handle_enrich(self, request: web.Request) -> web.Response:
        enrichment_type = request.match_info["enrichment_type"]

        if enrichment_type not in SUPPORTED_ENRICHMENT_TYPES:
            return web.json_response(
                {"error": f"Unknown enrichment_type: {enrichment_type!r}. Supported: {sorted(SUPPORTED_ENRICHMENT_TYPES)}"},
                status=400,
            )

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        public_cluster_id = body.get("public_cluster_id", "")
        if not public_cluster_id:
            return web.json_response({"error": "public_cluster_id is required"}, status=400)

        refresh = bool(body.get("refresh", False))
        handler = self._handlers[enrichment_type]
        t0 = time.monotonic()

        try:
            lookup = await self._cache.get_or_compute(
                public_cluster_id,
                enrichment_type,
                refresh=refresh,
                compute=handler.compute,
                prompt_version=self._resolve_prompt_version(enrichment_type, handler),
                model_name=self._config.llm.model_name,
            )
        except Exception as exc:
            logger.error("Enrichment failed cluster=%s type=%s: %s", public_cluster_id, enrichment_type, exc)
            ENRICH_REQUESTS.labels(enrichment_type=enrichment_type, status="error").inc()
            return web.json_response({"error": str(exc)}, status=500)

        elapsed = time.monotonic() - t0
        ENRICH_LATENCY.labels(enrichment_type=enrichment_type).observe(elapsed)
        ENRICH_REQUESTS.labels(enrichment_type=enrichment_type, status=lookup.computed.status).inc()
        if lookup.cached:
            ENRICH_CACHE_HITS.labels(enrichment_type=enrichment_type).inc()

        self._health.last_processed_at = datetime.now(timezone.utc).isoformat()

        c = lookup.computed
        return web.json_response({
            "status": c.status,
            "result": c.result_json,
            "cached": lookup.cached,
            "model": {"provider": c.model_provider, "name": c.model_name},
            "prompt_version": c.prompt_version,
            "language": c.language,
            "analysis_mode": c.analysis_mode,
            "tokens": {"input": c.tokens_input, "output": c.tokens_output},
            "cost_usd": float(c.cost_usd),
            "latency_ms": c.latency_ms,
            "generated_at": self._health.last_processed_at,
            "is_llm_generated": True,
            "disclaimer": "This content was generated by an LLM and supplements (does not replace) base ML analytics.",
            "error": c.error_message,
        })

    async def _handle_summary(self, request: web.Request) -> web.Response:
        """POST /summary/{public_cluster_id}

        Body: {"kinds": [...], "language": "ru", "refresh": false, "triggered_by": "user"}
        Orchestrates parallel enrichment for all requested kinds, with caching in topic_summaries.
        """
        public_cluster_id = request.match_info["public_cluster_id"]
        if not public_cluster_id:
            return web.json_response({"error": "public_cluster_id is required"}, status=400)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        kinds: list[str] = body.get("kinds", _ALL_KINDS)
        language: str = body.get("language", "ru")
        refresh: bool = bool(body.get("refresh", False))
        triggered_by: str = body.get("triggered_by", "user")

        unknown = [k for k in kinds if k not in _KIND_TO_ENRICHMENT_TYPE]
        if unknown:
            return web.json_response(
                {"error": f"Unknown kinds: {unknown}. Supported: {_ALL_KINDS}"}, status=400
            )

        started_at = datetime.now(timezone.utc)
        repo = ClusterContextRepository(self._pool)

        try:
            dto = await repo.fetch(public_cluster_id)
        except Exception as exc:
            logger.error("Failed to fetch cluster data cluster=%s: %s", public_cluster_id, exc)
            return web.json_response({"error": "Failed to fetch cluster data"}, status=500)

        lang_for_enrichment = language if language in ("ru", "en") else "other"
        fingerprint = fp.input_fingerprint(dto.model_dump(mode="json"))

        async def _compute_kind(kind: str) -> tuple[str, dict[str, Any], str, str, str]:
            enrichment_type = _KIND_TO_ENRICHMENT_TYPE[kind]
            handler: EnrichmentHandler = self._handlers[enrichment_type]
            prompt_version = self._resolve_prompt_version(enrichment_type, handler)

            cached = await repo.read_summary(
                public_cluster_id, kind, lang_for_enrichment, fingerprint, refresh
            )
            if cached is not None:
                return (
                    kind,
                    {**cached.payload, "status": cached.status, "prompt_version": cached.prompt_version},
                    cached.status,
                    cached.model_provider,
                    cached.model_name,
                )

            computed = await handler.compute(dto)
            payload = computed.result_json or {}
            try:
                await repo.upsert_summary(
                    public_cluster_id=public_cluster_id,
                    summary_kind=kind,
                    language=lang_for_enrichment,
                    prompt_version=computed.prompt_version or prompt_version,
                    model_provider=computed.model_provider,
                    model_name=computed.model_name,
                    input_fingerprint=fingerprint,
                    payload=payload,
                    status=computed.status,
                )
            except Exception as exc:
                logger.warning("Failed to upsert summary kind=%s: %s", kind, exc)

            return (
                kind,
                {**payload, "status": computed.status, "prompt_version": computed.prompt_version},
                computed.status,
                computed.model_provider,
                computed.model_name,
            )

        results = await asyncio.gather(
            *[_compute_kind(k) for k in kinds], return_exceptions=True
        )

        summaries: dict[str, Any] = {}
        kinds_succeeded: list[str] = []
        kinds_failed: list[str] = []
        total_cost_usd = 0.0
        total_latency_ms = 0
        model_provider = "unknown"
        model_name = "unknown"

        for item in results:
            if isinstance(item, Exception):
                logger.error("Kind compute error: %s", item)
                kinds_failed.append("?")
                continue
            kind, payload, status, mprov, mname = item
            summaries[kind] = payload
            if status in ("ok", "ok_baseline"):
                kinds_succeeded.append(kind)
                model_provider = mprov
                model_name = mname
            else:
                kinds_failed.append(kind)

        try:
            await repo.record_run(
                public_cluster_id=public_cluster_id,
                triggered_by=triggered_by,
                language=lang_for_enrichment,
                kinds_requested=kinds,
                kinds_succeeded=kinds_succeeded,
                kinds_failed=kinds_failed,
                total_cost_usd=total_cost_usd,
                total_latency_ms=total_latency_ms,
                started_at=started_at,
            )
        except Exception as exc:
            logger.warning("Failed to record summary run: %s", exc)

        self._health.last_processed_at = datetime.now(timezone.utc).isoformat()

        return web.json_response({
            "public_cluster_id": public_cluster_id,
            "language": lang_for_enrichment,
            "model": {"provider": model_provider, "name": model_name},
            "generated_at": self._health.last_processed_at,
            "summaries": summaries,
        })

    def _resolve_prompt_version(self, enrichment_type: str, handler) -> str:
        try:
            lang = "en"
            _, version = handler._registry.get(enrichment_type, lang)
            return version
        except Exception:
            return "v1"
