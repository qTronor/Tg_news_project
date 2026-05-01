from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from llm_enricher.budget import DailyBudgetTracker
from llm_enricher.cache import EnrichmentCache
from llm_enricher.config import AppConfig
from llm_enricher.handlers import build_handlers
from llm_enricher.metrics import ENRICH_CACHE_HITS, ENRICH_LATENCY, ENRICH_REQUESTS
from llm_enricher.providers.base import LLMProvider
from llm_enricher.providers.mistral import MistralProvider
from llm_enricher.providers.mock import MockProvider
from llm_enricher.repository import ClusterContextRepository
from llm_enricher.schemas import SUPPORTED_ENRICHMENT_TYPES

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

    def _resolve_prompt_version(self, enrichment_type: str, handler) -> str:
        try:
            lang = "en"
            _, version = handler._registry.get(enrichment_type, lang)
            return version
        except Exception:
            return "v1"
