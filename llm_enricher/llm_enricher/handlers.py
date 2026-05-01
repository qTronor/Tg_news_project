from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from llm_enricher.budget import DailyBudgetTracker
from llm_enricher.cache import ComputedResult
from llm_enricher.config import AppConfig
from llm_enricher.metrics import (
    CIRCUIT_BREAKER_OPEN,
    COST_USD,
    LLM_CALL_LATENCY,
    TOKENS_USED,
)
from llm_enricher.providers.base import (
    LLMProvider,
    ProviderInvalidOutputError,
    ProviderTransientError,
)
from llm_enricher.prompts import PromptRegistry
from llm_enricher.schemas import (
    MAX_TOKENS,
    OUTPUT_SCHEMAS,
    ClusterEnrichmentInput,
)

logger = logging.getLogger("llm_enricher.handlers")


def _fmt_entities(entities: list) -> str:
    if not entities:
        return "(none)"
    return "\n".join(
        f"- {e.normalized_text} [{e.entity_type}] ({e.mention_count} mentions)"
        for e in entities
    )


def _fmt_messages(messages: list) -> str:
    if not messages:
        return "(none)"
    lines = []
    for i, m in enumerate(messages[:5], 1):
        preview = (m.text or "")[:300].replace("\n", " ")
        lines.append(f"{i}. [{m.channel}] {preview}")
    return "\n".join(lines)


def _fmt_evolution_events(events: list) -> str:
    if not events:
        return "(none)"
    return "\n".join(f"- {e.event_type} (severity={e.severity:.2f}): {e.summary}" for e in events)


def _fmt_new_channels(buckets: list) -> str:
    if not buckets:
        return "(none)"
    latest = buckets[0]
    channels = latest.new_channels or []
    return ", ".join(channels) if channels else "(none)"


def _fmt_novelty_features(features: Optional[dict]) -> str:
    if not features:
        return "(none)"
    keys = ["novel_entity_count", "new_channel_count", "unique_entities", "first_seen", "last_seen"]
    return "\n".join(f"- {k}: {features.get(k)}" for k in keys if k in features)


class EnrichmentHandler:
    def __init__(
        self,
        enrichment_type: str,
        provider: LLMProvider,
        registry: PromptRegistry,
        budget: DailyBudgetTracker,
        config: AppConfig,
    ) -> None:
        self._type = enrichment_type
        self._provider = provider
        self._registry = registry
        self._budget = budget
        self._config = config
        self._schema = OUTPUT_SCHEMAS[enrichment_type]
        self._max_tokens = MAX_TOKENS[enrichment_type]

    async def compute(self, dto: ClusterEnrichmentInput) -> ComputedResult:
        lang = dto.language if dto.language in ("ru", "en") else "other"
        template, prompt_version = self._registry.get(self._type, lang)

        prompt = self._build_prompt(template, dto, lang)

        # Estimate cost before calling
        estimated_in = len(prompt) // 4
        estimated_cost = self._budget.estimate_cost(estimated_in, self._max_tokens)
        if not await self._budget.check_and_reserve(estimated_cost):
            return ComputedResult(
                result_json=None,
                status="budget_exhausted",
                error_message="Daily LLM budget exceeded",
                tokens_input=0,
                tokens_output=0,
                cost_usd=0.0,
                latency_ms=0,
                prompt_version=prompt_version,
                model_provider=self._provider.name,
                model_name=self._provider.model_name,
                language=dto.language,
                analysis_mode=dto.analysis_mode,
            )

        t0 = time.monotonic()
        actual_cost = 0.0
        try:
            result = await self._provider.generate_structured(
                prompt,
                self._schema,
                max_tokens=self._max_tokens,
                temperature=self._config.llm.temperature,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            actual_cost = self._budget.estimate_cost(result.tokens_input, result.tokens_output)
            await self._budget.record_actual(actual_cost, estimated_cost)

            TOKENS_USED.labels(provider=self._provider.name, direction="input").inc(result.tokens_input)
            TOKENS_USED.labels(provider=self._provider.name, direction="output").inc(result.tokens_output)
            COST_USD.labels(provider=self._provider.name).inc(actual_cost)
            LLM_CALL_LATENCY.labels(provider=self._provider.name).observe((time.monotonic() - t0))

            return ComputedResult(
                result_json=result.data,
                status="ok",
                error_message=None,
                tokens_input=result.tokens_input,
                tokens_output=result.tokens_output,
                cost_usd=actual_cost,
                latency_ms=latency_ms,
                prompt_version=prompt_version,
                model_provider=self._provider.name,
                model_name=self._provider.model_name,
                language=dto.language,
                analysis_mode=dto.analysis_mode,
            )

        except ProviderInvalidOutputError as exc:
            await self._budget.record_actual(0.0, estimated_cost)
            logger.warning("Invalid LLM output for %s: %s", self._type, exc)
            return self._error_result(str(exc), prompt_version, dto, t0)

        except (ProviderTransientError, Exception) as exc:
            await self._budget.record_actual(0.0, estimated_cost)
            if "CircuitBreaker" in type(exc).__name__ or "circuit" in str(exc).lower():
                CIRCUIT_BREAKER_OPEN.labels(provider=self._provider.name).inc()
            logger.error("LLM call failed for %s: %s", self._type, exc)
            return self._error_result(str(exc), prompt_version, dto, t0)

    def _error_result(
        self, msg: str, prompt_version: str, dto: ClusterEnrichmentInput, t0: float
    ) -> ComputedResult:
        return ComputedResult(
            result_json=None,
            status="error",
            error_message=msg[:500],
            tokens_input=0,
            tokens_output=0,
            cost_usd=0.0,
            latency_ms=int((time.monotonic() - t0) * 1000),
            prompt_version=prompt_version,
            model_provider=self._provider.name,
            model_name=self._provider.model_name,
            language=dto.language,
            analysis_mode=dto.analysis_mode,
        )

    def _build_prompt(
        self, template: Any, dto: ClusterEnrichmentInput, lang: str
    ) -> str:
        if self._type == "cluster_summary":
            return template.safe_substitute(
                cluster_id=dto.public_cluster_id,
                importance_level=dto.importance_level or "unknown",
                top_entities=_fmt_entities(dto.top_entities),
                representative_messages=_fmt_messages(dto.representative_messages),
            )
        elif self._type == "cluster_explanation":
            return template.safe_substitute(
                cluster_id=dto.public_cluster_id,
                importance_score=f"{dto.importance_score:.3f}" if dto.importance_score is not None else "N/A",
                importance_level=dto.importance_level or "unknown",
                score_breakdown=json.dumps(dto.score_breakdown or {}, ensure_ascii=False, indent=2),
                features=json.dumps(dto.features or {}, ensure_ascii=False, indent=2),
                top_entities=_fmt_entities(dto.top_entities),
                sentiment_summary=json.dumps(
                    dto.sentiment_summary.model_dump() if dto.sentiment_summary else {}, ensure_ascii=False
                ),
            )
        elif self._type == "novelty_explanation":
            return template.safe_substitute(
                cluster_id=dto.public_cluster_id,
                novelty_features=_fmt_novelty_features(dto.features),
                evolution_events=_fmt_evolution_events(dto.evolution_events),
                new_channels=_fmt_new_channels(dto.timeline_buckets),
            )
        elif self._type == "cluster_label":
            return template.safe_substitute(
                cluster_id=dto.public_cluster_id,
                top_entities=_fmt_entities(dto.top_entities),
                representative_messages=_fmt_messages(dto.representative_messages),
            )
        else:
            raise ValueError(f"Unknown enrichment_type: {self._type!r}")


def build_handlers(
    provider: LLMProvider,
    budget: DailyBudgetTracker,
    config: AppConfig,
    prompts_root: Optional[Path] = None,
) -> dict[str, EnrichmentHandler]:
    registry = PromptRegistry(prompts_root)
    return {
        etype: EnrichmentHandler(etype, provider, registry, budget, config)
        for etype in ("cluster_summary", "cluster_explanation", "novelty_explanation", "cluster_label")
    }
