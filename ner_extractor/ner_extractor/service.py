from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

import asyncpg
import pymorphy2
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from aiohttp import web
from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ner_extractor.config import AppConfig
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

NATASHA_TYPE_MAP = {"PER": "PERSON", "ORG": "ORG", "LOC": "LOC"}

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
    extracted_at
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9,
    $10, $11, $12, $13, $14, $15, $16, $17, $18
)
RETURNING id;
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
    normalized: Optional[str]


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

        logger.info("loading natasha NER models")
        self._segmenter = Segmenter()
        emb = NewsEmbedding()
        self._ner_tagger = NewsNERTagger(emb)
        self._morph = pymorphy2.MorphAnalyzer()
        logger.info("natasha NER models loaded")

    async def start(self) -> None:
        await self._start_db()
        await self._start_kafka()
        await self._start_http()
        self._health.ready = True
        logger.info("service started")

    async def stop(self) -> None:
        self._health.ready = False
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

                entities = self._extract_entities(context.original_text)
                await conn.execute(DELETE_ENTITY_RELATIONS_SQL, preprocessed_id)
                await conn.execute(DELETE_NER_RESULTS_SQL, preprocessed_id)
                processing_time_ms = (
                    time.monotonic() - processing_started
                ) * 1000.0

                for ent in entities:
                    await conn.fetchval(
                        INSERT_NER_RESULT_SQL,
                        preprocessed_id,
                        context.message_id,
                        context.channel,
                        context.event_id,
                        ent.text,
                        ent.entity_type,
                        ent.start,
                        ent.end,
                        self._config.model.confidence,
                        ent.normalized,
                        None,
                        [],
                        json.dumps({"source": "natasha"}),
                        "natasha",
                        self._config.model.version,
                        now_dt,
                        context.trace_id_uuid,
                        now_dt,
                    )
                    ENTITIES_EXTRACTED.labels(entity_type=ent.entity_type).inc()

                relations = self._build_co_occurrence_relations(entities)
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
            context, entities, relations, now_iso, processing_time_ms
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

    # ── NER inference ───────────────────────────────────────────────

    def _extract_entities(self, text: str) -> list[EntitySpan]:
        if not text or not text.strip():
            return []

        doc = Doc(text)
        doc.segment(self._segmenter)
        doc.tag_ner(self._ner_tagger)

        entities: list[EntitySpan] = []
        seen: set[tuple[str, int, int]] = set()
        for span in doc.spans:
            if span.type not in NATASHA_TYPE_MAP:
                continue
            normalized = self._normalize_entity(span.text)
            if len(normalized) < self._config.model.min_entity_length:
                continue
            if normalized.isnumeric():
                continue
            dedup_key = (normalized.lower(), span.start, span.stop)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            mapped_type = NATASHA_TYPE_MAP[span.type]
            canonical = self._canonicalize(normalized, span.type)

            entities.append(
                EntitySpan(
                    text=span.text,
                    entity_type=mapped_type,
                    start=span.start,
                    end=span.stop,
                    normalized=canonical,
                )
            )
        return entities

    def _normalize_entity(self, text: str) -> str:
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

    @staticmethod
    def _build_co_occurrence_relations(
        entities: list[EntitySpan],
    ) -> list[tuple[str, str, str, str]]:
        if len(entities) < 2:
            return []
        relations: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for a, b in itertools.combinations(entities, 2):
            norm_a = (a.normalized or a.text).lower()
            norm_b = (b.normalized or b.text).lower()
            if norm_a == norm_b:
                continue
            pair_key = tuple(sorted([norm_a, norm_b]))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            relations.append((
                a.normalized or a.text,
                b.normalized or b.text,
                a.entity_type,
                b.entity_type,
            ))
        return relations

    # ── output building ─────────────────────────────────────────────

    def _build_enriched_event(
        self,
        context: MessageContext,
        entities: list[EntitySpan],
        relations: list[tuple[str, str, str, str]],
        now_iso: str,
        processing_time_ms: float,
    ) -> dict:
        entities_payload = [
            {
                "text": ent.text,
                "type": ent.entity_type,
                "start": ent.start,
                "end": ent.end,
                "confidence": self._config.model.confidence,
                "normalized": ent.normalized,
                "wikidata_id": None,
            }
            for ent in entities
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
                "model": {
                    "name": "natasha",
                    "version": self._config.model.version,
                    "framework": "natasha",
                },
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
