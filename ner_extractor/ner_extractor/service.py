from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Tuple
from uuid import UUID

import asyncpg
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ner_extractor.backends import Entity, NatashaRuBackend, TransformersEnBackend
from ner_extractor.config import AppConfig
from ner_extractor.providers import (
    NatashaProvider,
    ProviderChain,
    RuleBasedAliasProvider,
    TransformerNERProvider,
)
from ner_extractor.resolver import (
    CanonicalResolver,
    ResolvedEntity,
    ResolverConfig,
    load_rules_from_db,
)
from ner_extractor.metrics import (
    ENTITIES_EXTRACTED,
    MESSAGES_CONSUMED,
    MESSAGES_DLQ,
    MESSAGES_PROCESSED,
    PROCESSING_LATENCY,
)
from ner_extractor.schemas import JsonSchemaValidator, SchemaValidationError
from ner_extractor.utils import decode_kafka_key, parse_iso_datetime, utc_now_iso


logger = logging.getLogger("ner_extractor")

INSERT_PROCESSED_EVENT_SQL = """
INSERT INTO processed_events (event_id, event_type, event_timestamp, consumer_id, status)
VALUES ($1, $2, $3, $4, 'processing')
ON CONFLICT (event_id) DO UPDATE
SET status = 'processing',
    retry_count = processed_events.retry_count + 1,
    processing_started_at = NOW(),
    error_message = NULL
WHERE processed_events.status != 'completed'
RETURNING status;
"""

UPDATE_PROCESSED_COMPLETED_SQL = """
UPDATE processed_events
SET status = 'completed',
    processing_completed_at = NOW(),
    error_message = NULL
WHERE event_id = $1;
"""

UPDATE_PROCESSED_STATUS_SQL = """
UPDATE processed_events
SET status = $2::varchar,
    error_message = $3::text,
    processing_completed_at = CASE
        WHEN $2::varchar = 'failed' THEN NOW()
        ELSE processing_completed_at
    END
WHERE event_id = $1;
"""

SELECT_PREPROCESSED_ID_SQL = """
SELECT id FROM preprocessed_messages
WHERE channel = $1 AND message_id = $2;
"""

INSERT_NER_RESULT_SQL = """
INSERT INTO ner_results (
    preprocessed_message_id,
    message_id,
    channel,
    event_id,
    entity_text,
    entity_type,
    start_pos,
    end_pos,
    confidence,
    normalized_text,
    wikidata_id,
    aliases,
    entity_metadata,
    model_name,
    model_version,
    event_timestamp,
    trace_id,
    extracted_at,
    model_backend,
    model_language,
    entity_canonical_id
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9,
    $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21
)
RETURNING id;
"""

INSERT_NER_MODEL_RUN_SQL = """
INSERT INTO ner_model_runs (
    preprocessed_message_id,
    provider_name,
    provider_version,
    language,
    entity_count,
    latency_ms,
    success,
    error
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
"""

INSERT_ENTITY_RELATION_SQL = """
INSERT INTO entity_relations (
    preprocessed_message_id,
    message_id,
    channel,
    subject,
    predicate,
    object,
    confidence,
    subject_type,
    object_type,
    event_timestamp,
    trace_id
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
RETURNING id;
"""

DELETE_NER_RESULTS_SQL = """
DELETE FROM ner_results
WHERE preprocessed_message_id = $1;
"""

DELETE_ENTITY_RELATIONS_SQL = """
DELETE FROM entity_relations
WHERE preprocessed_message_id = $1;
"""


class ProcessingOutcome(Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    DLQ = "dlq"
    RETRY_PENDING = "retry_pending"


class NonRetriableError(Exception):
    def __init__(self, message: str, reason: str = "invalid_payload") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class EntitySpan:
    text: str
    entity_type: str
    start: int
    end: int
    normalized: Optional[str] = None
    confidence: float = 1.0


@dataclass
class MessageContext:
    event_id: str
    processing_event_id: str
    event_type: str
    event_timestamp: str
    event_timestamp_dt: datetime
    trace_id: str
    trace_id_uuid: UUID
    message_id: int
    channel: str
    original_text: str
    original_language: str
    analysis_mode: str
    is_supported_for_full_analysis: bool
    payload: dict
    key: str
    topic: str
    partition: int
    offset: int


@dataclass
class HealthState:
    ready: bool = False
    kafka_connected: bool = False
    postgres_connected: bool = False
    last_processed_at: Optional[str] = None
    last_error: Optional[str] = None


class NerExtractorService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._pool: Optional[asyncpg.Pool] = None
        self._health = HealthState()
        self._input_validator = JsonSchemaValidator(
            config.schemas.preprocessed_message_path
        )
        self._output_validator = JsonSchemaValidator(config.schemas.ner_enriched_path)
        self._stop_event = asyncio.Event()
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None
        self._listen_task: Optional[asyncio.Task] = None

        # ── NER provider chain ─────────────────────────────────────────
        ru_cfg = config.models.ru
        logger.info("loading natasha NER models")
        natasha_provider = NatashaProvider(
            version=ru_cfg.version,
            min_entity_length=ru_cfg.min_entity_length,
        )
        logger.info("natasha NER models loaded")

        en_cfg = config.models.en
        providers = [natasha_provider]
        if en_cfg.enabled:
            providers.append(
                TransformerNERProvider(
                    name=en_cfg.name,
                    version=en_cfg.version,
                    device=en_cfg.device,
                    batch_size=en_cfg.batch_size,
                    min_entity_length=en_cfg.min_entity_length,
                    confidence_threshold=en_cfg.confidence_threshold,
                    cache_dir=en_cfg.cache_dir,
                )
            )
            logger.info("EN NER provider configured model=%s (lazy load)", en_cfg.name)

        canonical_cfg = config.canonical
        if canonical_cfg.enable_llm_ner:
            from ner_extractor.providers.llm import LLMNERProvider
            providers.append(LLMNERProvider())

        self._provider_chain = ProviderChain(providers)

        # Keep legacy backend refs for backward-compat (e.g. tests that mock them)
        self._ru_backend = natasha_provider._backend
        self._en_backend = providers[1]._backend if en_cfg.enabled else None

        # ── canonical resolver ─────────────────────────────────────────
        self._resolver = CanonicalResolver(
            ResolverConfig(
                enable_canonical_resolution=canonical_cfg.enable_canonical_resolution,
                enable_embedding_match=canonical_cfg.enable_embedding_match,
                fuzzy_threshold=canonical_cfg.fuzzy_threshold,
                auto_create_threshold=canonical_cfg.auto_create_threshold,
                link_threshold=canonical_cfg.link_threshold,
                cache_size=canonical_cfg.resolver_cache_size,
            )
        )

    async def start(self) -> None:
        await self._start_db()
        await self._load_initial_rules()
        await self._start_kafka()
        await self._start_http()
        self._listen_task = asyncio.create_task(self._listen_invalidate())
        self._health.ready = True
        logger.info("service started")

    async def stop(self) -> None:
        self._health.ready = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._consumer is not None:
            await self._consumer.stop()
        if self._producer is not None:
            await self._producer.stop()
        if self._pool is not None:
            await self._pool.close()
        if self._web_runner is not None:
            await self._web_runner.cleanup()
        logger.info("service stopped")

    async def run(self) -> None:
        await self.start()
        try:
            assert self._consumer is not None
            async for record in self._consumer:
                if self._stop_event.is_set():
                    break
                await self._handle_record(record)
        finally:
            await self.stop()

    def request_stop(self) -> None:
        self._stop_event.set()

    # ── infrastructure ──────────────────────────────────────────────

    async def _start_db(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn(),
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
        self._health.postgres_connected = True

    async def _start_kafka(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self._config.kafka.input_topic,
            bootstrap_servers=self._config.kafka.bootstrap_servers,
            group_id=self._config.kafka.consumer_group,
            client_id=self._config.kafka.client_id,
            enable_auto_commit=False,
            auto_offset_reset=self._config.kafka.auto_offset_reset,
            max_poll_records=self._config.kafka.max_poll_records,
            session_timeout_ms=self._config.kafka.session_timeout_ms,
            request_timeout_ms=self._config.kafka.request_timeout_ms,
            max_partition_fetch_bytes=self._config.kafka.max_partition_fetch_bytes,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._config.kafka.bootstrap_servers,
            client_id=self._config.kafka.client_id,
            acks="all",
        )
        await self._consumer.start()
        await self._producer.start()
        self._health.kafka_connected = True

    async def _start_http(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/metrics", self._handle_metrics)
        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()
        self._health_site = web.TCPSite(
            self._web_runner, self._config.health.host, self._config.health.port
        )
        await self._health_site.start()
        if (
            self._config.metrics.host,
            self._config.metrics.port,
        ) != (
            self._config.health.host,
            self._config.health.port,
        ):
            self._metrics_site = web.TCPSite(
                self._web_runner,
                self._config.metrics.host,
                self._config.metrics.port,
            )
            await self._metrics_site.start()

    async def _handle_health(self, request: web.Request) -> web.Response:
        payload = {
            "status": "ok" if self._health.ready else "starting",
            "ready": self._health.ready,
            "kafka_connected": self._health.kafka_connected,
            "postgres_connected": self._health.postgres_connected,
            "last_processed_at": self._health.last_processed_at,
            "last_error": self._health.last_error,
        }
        return web.json_response(payload)

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        return web.Response(
            body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    # ── record handling ─────────────────────────────────────────────

    async def _handle_record(self, record) -> None:
        MESSAGES_CONSUMED.inc()
        start_time = time.monotonic()
        outcome = await self._process_with_retry(record)
        PROCESSING_LATENCY.observe(time.monotonic() - start_time)

        if outcome in {
            ProcessingOutcome.SUCCESS,
            ProcessingOutcome.DUPLICATE,
            ProcessingOutcome.DLQ,
        }:
            await self._commit_record(record)

    async def _commit_record(self, record) -> None:
        if self._consumer is None:
            return
        tp = TopicPartition(record.topic, record.partition)
        await self._consumer.commit(
            {tp: OffsetAndMetadata(record.offset + 1, "")}
        )

    async def _process_with_retry(self, record) -> ProcessingOutcome:
        try:
            context = self._build_context(record)
        except NonRetriableError as exc:
            logger.warning(
                "non-retriable error: %s topic=%s partition=%s offset=%s",
                exc,
                record.topic,
                record.partition,
                record.offset,
            )
            self._health.last_error = str(exc)
            await self._send_to_dlq(record, exc, None, exc.reason)
            MESSAGES_DLQ.inc()
            MESSAGES_PROCESSED.labels(status="dlq").inc()
            self._health.last_processed_at = utc_now_iso()
            return ProcessingOutcome.DLQ

        logger.info(
            "processing event_id=%s trace_id=%s",
            context.event_id,
            context.trace_id,
        )

        for attempt in range(1, self._config.retry.max_attempts + 1):
            try:
                outcome = await self._process_once(context)
                self._health.last_processed_at = utc_now_iso()
                return outcome
            except NonRetriableError as exc:
                logger.warning(
                    "non-retriable processing error event_id=%s reason=%s",
                    context.event_id,
                    exc.reason,
                )
                await self._update_processing_status(
                    context.processing_event_id, "failed", str(exc)
                )
                dlq_sent = await self._send_to_dlq(
                    record, exc, context, exc.reason
                )
                if dlq_sent:
                    MESSAGES_DLQ.inc()
                    MESSAGES_PROCESSED.labels(status="dlq").inc()
                    self._health.last_processed_at = utc_now_iso()
                    return ProcessingOutcome.DLQ
                return ProcessingOutcome.RETRY_PENDING
            except Exception as exc:  # noqa: BLE001 - service-level retry
                logger.exception(
                    "processing failed attempt=%s event_id=%s",
                    attempt,
                    context.event_id,
                )
                self._health.last_error = str(exc)
                await self._update_processing_status(
                    context.processing_event_id,
                    "retrying"
                    if attempt < self._config.retry.max_attempts
                    else "failed",
                    str(exc),
                )
                if attempt < self._config.retry.max_attempts:
                    await asyncio.sleep(self._backoff_seconds(attempt))
                    continue

                dlq_sent = await self._send_to_dlq(
                    record, exc, context, "processing_error"
                )
                if dlq_sent:
                    MESSAGES_DLQ.inc()
                    MESSAGES_PROCESSED.labels(status="dlq").inc()
                    self._health.last_processed_at = utc_now_iso()
                    return ProcessingOutcome.DLQ
                return ProcessingOutcome.RETRY_PENDING
        return ProcessingOutcome.RETRY_PENDING

    # ── context building ────────────────────────────────────────────

    def _build_context(self, record) -> MessageContext:
        raw_bytes = record.value
        if raw_bytes is None:
            raise NonRetriableError("record value is empty", reason="invalid_payload")
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - input parsing
            raise NonRetriableError(
                f"invalid json payload: {exc}", reason="invalid_json"
            ) from exc

        try:
            self._input_validator.validate(payload)
        except SchemaValidationError as exc:
            raise NonRetriableError(str(exc), reason="invalid_schema") from exc

        event_id = payload["event_id"]
        event_timestamp = payload["event_timestamp"]
        trace_id = payload["trace_id"]
        message_id = payload["payload"]["message_id"]
        channel = payload["payload"]["channel"]
        original_text = payload["payload"].get("original_text", "")
        original_language = payload["payload"].get(
            "original_language",
            payload["payload"].get("language", "und"),
        )
        analysis_mode = payload["payload"].get("analysis_mode", "full")
        is_supported_for_full_analysis = payload["payload"].get(
            "is_supported_for_full_analysis",
            original_language in {"ru", "en"},
        )

        try:
            event_timestamp_dt = parse_iso_datetime(event_timestamp)
            trace_id_uuid = UUID(trace_id)
        except ValueError as exc:
            raise NonRetriableError(
                f"invalid value: {exc}", reason="invalid_payload"
            ) from exc

        expected_event_id = f"{channel}:{message_id}"
        if event_id != expected_event_id:
            raise NonRetriableError(
                f"event_id mismatch expected={expected_event_id} got={event_id}",
                reason="invalid_event_id",
            )

        key = decode_kafka_key(record.key)
        if key is None:
            raise NonRetriableError("missing Kafka message key", reason="missing_key")
        if key != event_id:
            raise NonRetriableError(
                f"message key mismatch expected={event_id} got={key}",
                reason="invalid_key",
            )

        processing_event_id = f"{self._config.consumer_id}:{event_id}"

        return MessageContext(
            event_id=event_id,
            processing_event_id=processing_event_id,
            event_type=payload["event_type"],
            event_timestamp=event_timestamp,
            event_timestamp_dt=event_timestamp_dt,
            trace_id=trace_id,
            trace_id_uuid=trace_id_uuid,
            message_id=message_id,
            channel=channel,
            original_text=original_text,
            original_language=original_language,
            analysis_mode=analysis_mode,
            is_supported_for_full_analysis=bool(is_supported_for_full_analysis),
            payload=payload,
            key=key,
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
        )

    # ── core processing ─────────────────────────────────────────────

    async def _process_once(self, context: MessageContext) -> ProcessingOutcome:
        if self._pool is None or self._producer is None:
            raise RuntimeError("service not initialized")

        processing_started = time.monotonic()
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat().replace("+00:00", "Z")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                should_process = await self._begin_processing(conn, context)
                if not should_process:
                    logger.info("duplicate event_id=%s", context.event_id)
                    MESSAGES_PROCESSED.labels(status="duplicate").inc()
                    return ProcessingOutcome.DUPLICATE

                preprocessed_id = await conn.fetchval(
                    SELECT_PREPROCESSED_ID_SQL,
                    context.channel,
                    context.message_id,
                )
                if preprocessed_id is None:
                    raise NonRetriableError(
                        f"preprocessed message not found "
                        f"channel={context.channel} message_id={context.message_id}",
                        reason="missing_upstream",
                    )

                if (
                    context.analysis_mode != "full"
                    or not context.is_supported_for_full_analysis
                ):
                    logger.info(
                        "skipping NER for event_id=%s language=%s analysis_mode=%s",
                        context.event_id,
                        context.original_language,
                        context.analysis_mode,
                    )
                    await conn.execute(
                        UPDATE_PROCESSED_COMPLETED_SQL,
                        context.processing_event_id,
                    )
                    MESSAGES_PROCESSED.labels(status="skipped_unsupported").inc()
                    return ProcessingOutcome.SUCCESS

                loop = asyncio.get_event_loop()
                entities, run_metrics_list = await loop.run_in_executor(
                    None,
                    self._provider_chain.extract_with_metrics,
                    context.original_text,
                    context.original_language,
                )

                await conn.execute(DELETE_ENTITY_RELATIONS_SQL, preprocessed_id)
                await conn.execute(DELETE_NER_RESULTS_SQL, preprocessed_id)
                processing_time_ms = (
                    time.monotonic() - processing_started
                ) * 1000.0

                # Write per-provider run metrics
                for metrics in run_metrics_list:
                    await conn.execute(
                        INSERT_NER_MODEL_RUN_SQL,
                        preprocessed_id,
                        metrics.provider_name,
                        metrics.provider_version,
                        metrics.language,
                        metrics.entity_count,
                        metrics.latency_ms,
                        metrics.success,
                        metrics.error,
                    )

                # Insert ner_results and collect row ids for resolver
                ner_result_ids: List[str] = []
                primary_model_name = run_metrics_list[0].provider_name if run_metrics_list else "natasha"
                for ent in entities:
                    row_id = await conn.fetchval(
                        INSERT_NER_RESULT_SQL,
                        preprocessed_id,           # $1
                        context.message_id,        # $2
                        context.channel,           # $3
                        context.event_id,          # $4
                        ent.text,                  # $5
                        ent.entity_type,           # $6
                        ent.start,                 # $7
                        ent.end,                   # $8
                        ent.confidence,            # $9
                        ent.normalized,            # $10
                        None,                      # $11 wikidata_id
                        [],                        # $12 aliases
                        json.dumps({"source": primary_model_name}),  # $13
                        primary_model_name,        # $14
                        "1.0.0",                   # $15
                        now_dt,                    # $16
                        context.trace_id_uuid,     # $17
                        now_dt,                    # $18
                        primary_model_name,        # $19 model_backend
                        context.original_language, # $20 model_language
                        None,                      # $21 entity_canonical_id (filled after resolve)
                    )
                    ner_result_ids.append(str(row_id))
                    ENTITIES_EXTRACTED.labels(entity_type=ent.entity_type).inc()

                # Canonical resolution
                resolved_entities = await self._resolver.resolve_many(
                    conn, entities, ner_result_ids, context.original_language
                )

                # Back-fill canonical_id on ner_results rows
                for res, rid in zip(resolved_entities, ner_result_ids):
                    if res.canonical_id:
                        await conn.execute(
                            "UPDATE ner_results SET entity_canonical_id = $1 WHERE id = $2",
                            UUID(res.canonical_id),
                            UUID(rid),
                        )

                relations = self._build_co_occurrence_relations(resolved_entities)
                for subj, obj_, subj_type, obj_type in relations:
                    await conn.fetchval(
                        INSERT_ENTITY_RELATION_SQL,
                        preprocessed_id,
                        context.message_id,
                        context.channel,
                        subj,
                        "CO_OCCURS_WITH",
                        obj_,
                        1.0,
                        subj_type,
                        obj_type,
                        now_dt,
                        context.trace_id_uuid,
                    )

        enriched_event = self._build_enriched_event(
            context, resolved_entities, relations, run_metrics_list, now_iso, processing_time_ms
        )
        try:
            self._output_validator.validate(enriched_event)
        except SchemaValidationError as exc:
            raise NonRetriableError(
                f"output schema validation failed: {exc}",
                reason="output_schema_invalid",
            ) from exc

        await self._producer.send_and_wait(
            self._config.kafka.output_topic,
            json.dumps(enriched_event).encode("utf-8"),
            key=context.event_id.encode("utf-8"),
        )

        async with self._pool.acquire() as conn:
            await conn.execute(
                UPDATE_PROCESSED_COMPLETED_SQL, context.processing_event_id
            )

        MESSAGES_PROCESSED.labels(status="success").inc()
        return ProcessingOutcome.SUCCESS

    async def _begin_processing(
        self, conn: asyncpg.Connection, context: MessageContext
    ) -> bool:
        row = await conn.fetchrow(
            INSERT_PROCESSED_EVENT_SQL,
            context.processing_event_id,
            context.event_type,
            context.event_timestamp_dt,
            self._config.consumer_id,
        )
        return row is not None

    # ── rules / LISTEN/NOTIFY ────────────────────────────────────────

    async def _load_initial_rules(self) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            rules = await load_rules_from_db(conn)
            self._resolver.update_rules(rules)
        logger.info("loaded %d normalization rules", len(rules) if 'rules' in dir() else 0)

    async def _listen_invalidate(self) -> None:
        """Background task: LISTEN entity_resolver_invalidate and reload rules on NOTIFY."""
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.add_listener("entity_resolver_invalidate", self._on_invalidate)
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)
                await conn.remove_listener("entity_resolver_invalidate", self._on_invalidate)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("LISTEN entity_resolver_invalidate failed")

    def _on_invalidate(self, conn, pid, channel, payload) -> None:
        self._resolver.invalidate_cache()
        asyncio.create_task(self._load_initial_rules())
        logger.info("resolver cache invalidated payload=%s", payload)

    # ── co-occurrence relations ─────────────────────────────────────

    @staticmethod
    def _build_co_occurrence_relations(
        resolved_entities: List[ResolvedEntity],
    ) -> List[Tuple[str, str, str, str]]:
        if len(resolved_entities) < 2:
            return []

        def _entity_of(value):
            return getattr(value, "entity", value)

        def _canonical_id_of(value) -> Optional[str]:
            return getattr(value, "canonical_id", None)

        def _canonical_name_of(value) -> Optional[str]:
            return getattr(value, "canonical_name", None)

        relations: List[Tuple[str, str, str, str]] = []
        seen = set()
        for a, b in itertools.combinations(resolved_entities, 2):
            entity_a = _entity_of(a)
            entity_b = _entity_of(b)
            # Prefer canonical_id for dedup; fall back to normalized text
            key_a = _canonical_id_of(a) or (entity_a.normalized or entity_a.text).lower()
            key_b = _canonical_id_of(b) or (entity_b.normalized or entity_b.text).lower()
            if key_a == key_b:
                continue
            pair_key = tuple(sorted([key_a, key_b]))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            name_a = _canonical_name_of(a) or entity_a.normalized or entity_a.text
            name_b = _canonical_name_of(b) or entity_b.normalized or entity_b.text
            relations.append((name_a, name_b, entity_a.entity_type, entity_b.entity_type))
        return relations

    # ── output building ─────────────────────────────────────────────

    def _build_enriched_event(
        self,
        context: MessageContext,
        resolved_entities: List[ResolvedEntity],
        relations: List[Tuple[str, str, str, str]],
        run_metrics_list: list,
        now_iso: str,
        processing_time_ms: float,
    ) -> dict:
        primary_metrics = run_metrics_list[0] if run_metrics_list else None
        entities_payload = [
            {
                "text": res.entity.text,
                "type": res.entity.entity_type,
                "start": res.entity.start,
                "end": res.entity.end,
                "confidence": res.entity.confidence,
                "normalized": res.entity.normalized,
                "wikidata_id": None,
                "canonical_id": res.canonical_id,
                "canonical_name": res.canonical_name,
                "aliases": res.aliases,
            }
            for res in resolved_entities
        ]
        relations_payload = [
            {
                "subject": subj,
                "predicate": "CO_OCCURS_WITH",
                "object": obj_,
                "confidence": 1.0,
                "subject_type": subj_type,
                "object_type": obj_type,
            }
            for subj, obj_, subj_type, obj_type in relations
        ]
        model_info = {
            "name": primary_metrics.provider_name if primary_metrics else "natasha",
            "version": primary_metrics.provider_version if primary_metrics else "1.0.0",
            "framework": "chain",
            "backend": primary_metrics.provider_name if primary_metrics else "natasha",
            "language": context.original_language,
        }
        return {
            "event_id": context.event_id,
            "event_type": "ner_enriched",
            "event_timestamp": now_iso,
            "event_version": self._config.event_version,
            "source_system": self._config.source_system,
            "trace_id": context.trace_id,
            "payload": {
                "message_id": context.message_id,
                "channel": context.channel,
                "entities": entities_payload,
                "relations": relations_payload,
                "model": model_info,
                "extracted_at": now_iso,
                "processing_time_ms": round(processing_time_ms, 3),
            },
        }

    # ── error handling ──────────────────────────────────────────────

    async def _update_processing_status(
        self, event_id: str, status: str, error_message: str
    ) -> None:
        if self._pool is None:
            return
        truncated = error_message[:1000]
        async with self._pool.acquire() as conn:
            await conn.execute(
                UPDATE_PROCESSED_STATUS_SQL, event_id, status, truncated
            )

    async def _send_to_dlq(
        self,
        record,
        error: Exception,
        context: Optional[MessageContext],
        reason: str,
    ) -> bool:
        if self._producer is None:
            return False
        key = None
        if context is not None:
            key = context.event_id
        else:
            key = decode_kafka_key(record.key)
        if key is None:
            key = "unknown:0"
        headers = [
            ("error", str(error).encode("utf-8")),
            ("reason", reason.encode("utf-8")),
            ("service", self._config.service_name.encode("utf-8")),
        ]
        payload = record.value if record.value is not None else b""
        try:
            await self._producer.send_and_wait(
                self._config.kafka.dlq_topic,
                payload,
                key=key.encode("utf-8"),
                headers=headers,
            )
        except Exception:  # noqa: BLE001 - dlq fallback
            logger.exception("failed to publish to dlq")
            return False
        return True

    def _backoff_seconds(self, attempt: int) -> float:
        delay = self._config.retry.initial_backoff_seconds * (
            self._config.retry.backoff_multiplier ** (attempt - 1)
        )
        return min(delay, self._config.retry.max_backoff_seconds)
