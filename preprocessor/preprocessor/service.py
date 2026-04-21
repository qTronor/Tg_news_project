from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple
from uuid import UUID

import asyncpg
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from preprocessor.config import AppConfig
from preprocessor.metrics import (
    LANGUAGE_DETECTION_LATENCY,
    MESSAGES_BY_LANGUAGE,
    MESSAGES_CONSUMED,
    MESSAGES_DLQ,
    MESSAGES_PROCESSED,
    PROCESSING_LATENCY,
)
from preprocessor.language_detection import build_detector
from preprocessor.schemas import JsonSchemaValidator, SchemaValidationError
from preprocessor.text_processing import configure_detector, preprocess_text
from preprocessor.utils import (
    decode_kafka_key,
    parse_iso_datetime,
    parse_optional_iso_datetime,
    utc_now_iso,
)


logger = logging.getLogger("preprocessor")

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

INSERT_RAW_MESSAGE_SQL = """
INSERT INTO raw_messages (
    message_id,
    channel,
    channel_id,
    permalink,
    text,
    message_date,
    views,
    forwards,
    reactions,
    media,
    grouped_id,
    edit_date,
    reply_to_message_id,
    reply_to_top_message_id,
    author,
    post_author,
    is_forwarded,
    forward_from_channel,
    forward_from_channel_id,
    forward_from_message_id,
    forward_date,
    forward_origin_type,
    event_timestamp,
    trace_id
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
    $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24
)
ON CONFLICT (channel, message_id) DO NOTHING
RETURNING id;
"""

SELECT_RAW_MESSAGE_ID_SQL = """
SELECT id FROM raw_messages
WHERE channel = $1 AND message_id = $2;
"""

SELECT_RAW_MESSAGE_SQL = """
SELECT id, text FROM raw_messages
WHERE channel = $1 AND message_id = $2;
"""

INSERT_PREPROCESSED_SQL = """
INSERT INTO preprocessed_messages (
    raw_message_id,
    message_id,
    channel,
    event_id,
    original_text,
    cleaned_text,
    normalized_text,
    language,
    original_language,
    language_confidence,
    is_supported_for_full_analysis,
    analysis_mode,
    translation_status,
    tokens,
    sentences_count,
    word_count,
    has_urls,
    has_mentions,
    has_hashtags,
    urls,
    mentions,
    hashtags,
    normalized_text_hash,
    simhash64,
    url_fingerprints,
    primary_url_fingerprint,
    preprocessing_version,
    event_timestamp,
    trace_id,
    processing_time_ms
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
    $12, $13, $14, $15, $16, $17, $18, $19, $20, $21,
    $22, $23, $24, $25, $26, $27, $28, $29, $30
)
ON CONFLICT (channel, message_id) DO NOTHING
RETURNING id;
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


class MissingUpstreamError(Exception):
    def __init__(self, message: str = "raw message not found") -> None:
        super().__init__(message)
        self.reason = "missing_upstream"


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
    message_date_dt: Optional[datetime]
    edit_date_dt: Optional[datetime]
    forward_date_dt: Optional[datetime]
    raw_text: Optional[str]
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


class PreprocessorService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._pool: Optional[asyncpg.Pool] = None
        self._health = HealthState()
        self._raw_validator = JsonSchemaValidator(config.schemas.raw_message_path)
        self._persisted_validator = JsonSchemaValidator(
            config.schemas.persisted_message_path
        )
        self._preprocessed_validator = JsonSchemaValidator(
            config.schemas.preprocessed_message_path
        )
        self._stop_event = asyncio.Event()
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None
        self._detector_backend = self._install_language_detector()

    def _install_language_detector(self) -> str:
        """Build and install the process-wide language detector.

        Separated so that a detector-construction failure is logged with
        context and the preprocessor can still start with the heuristic
        fallback (no hard crash on e.g. a temporary download failure).
        """

        cfg = self._config.language_detection
        try:
            detector = build_detector(
                backend=cfg.backend,
                min_confidence=cfg.min_confidence,
                fasttext_model_path=cfg.fasttext_model_path,
                auto_download=cfg.auto_download,
            )
        except Exception as exc:  # noqa: BLE001 — degrade to heuristic rather than crash at import
            logger.warning(
                "failed to build language detector backend=%s, using heuristic: %s",
                cfg.backend,
                exc,
            )
            detector = build_detector(
                backend="heuristic",
                min_confidence=cfg.min_confidence,
                fasttext_model_path=None,
                auto_download=False,
            )
        configure_detector(detector)
        backend_name = getattr(detector, "name", "heuristic")
        logger.info(
            "language detector installed backend=%s min_confidence=%.2f full_langs=%s",
            backend_name,
            cfg.min_confidence,
            cfg.full_analysis_languages,
        )
        return backend_name

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
            while not self._stop_event.is_set():
                batch = await self._consumer.getmany(
                    timeout_ms=self._config.kafka.poll_timeout_ms,
                    max_records=self._config.kafka.max_poll_records,
                )
                if not batch:
                    await asyncio.sleep(0)
                    continue
                for _, records in batch.items():
                    for record in records:
                        if self._stop_event.is_set():
                            break
                        await self._handle_record(record)
        finally:
            await self.stop()

    def request_stop(self) -> None:
        self._stop_event.set()

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
            *self._config.kafka.input_topics,
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
        app.router.add_get("/healthz", self._handle_health)
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
                self._web_runner, self._config.metrics.host, self._config.metrics.port
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
            "language_detection": {
                "backend": self._detector_backend,
                "min_confidence": self._config.language_detection.min_confidence,
                "full_analysis_languages": list(
                    self._config.language_detection.full_analysis_languages
                ),
            },
        }
        return web.json_response(payload)

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        return web.Response(
            body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

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
        await self._consumer.commit({tp: OffsetAndMetadata(record.offset + 1, "")})

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
            "processing event_id=%s trace_id=%s topic=%s partition=%s offset=%s",
            context.event_id,
            context.trace_id,
            context.topic,
            context.partition,
            context.offset,
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
                dlq_sent = await self._send_to_dlq(record, exc, context, exc.reason)
                if dlq_sent:
                    MESSAGES_DLQ.inc()
                    MESSAGES_PROCESSED.labels(status="dlq").inc()
                    self._health.last_processed_at = utc_now_iso()
                    return ProcessingOutcome.DLQ
                return ProcessingOutcome.RETRY_PENDING
            except Exception as exc:  # noqa: BLE001 - service-level retry
                reason = "processing_error"
                if isinstance(exc, MissingUpstreamError):
                    reason = exc.reason
                logger.exception(
                    "processing failed attempt=%s event_id=%s topic=%s partition=%s offset=%s",
                    attempt,
                    context.event_id,
                    context.topic,
                    context.partition,
                    context.offset,
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

                dlq_sent = await self._send_to_dlq(record, exc, context, reason)
                if dlq_sent:
                    MESSAGES_DLQ.inc()
                    MESSAGES_PROCESSED.labels(status="dlq").inc()
                    self._health.last_processed_at = utc_now_iso()
                    return ProcessingOutcome.DLQ
                return ProcessingOutcome.RETRY_PENDING
        return ProcessingOutcome.RETRY_PENDING

    def _build_context(self, record) -> MessageContext:
        raw_bytes = record.value
        if raw_bytes is None:
            raise NonRetriableError("record value is empty", reason="invalid_payload")
        try:
            raw_text = raw_bytes.decode("utf-8")
            payload = json.loads(raw_text)
        except Exception as exc:  # noqa: BLE001 - input parsing
            raise NonRetriableError(
                f"invalid json payload: {exc}", reason="invalid_json"
            ) from exc

        event_type = payload.get("event_type")
        if event_type == "raw_message":
            validator = self._raw_validator
        elif event_type == "persisted":
            validator = self._persisted_validator
        else:
            raise NonRetriableError(
                f"unsupported event_type: {event_type}", reason="invalid_event_type"
            )

        try:
            validator.validate(payload)
        except SchemaValidationError as exc:
            raise NonRetriableError(str(exc), reason="invalid_schema") from exc

        event_id = payload["event_id"]
        event_timestamp = payload["event_timestamp"]
        trace_id = payload["trace_id"]
        message_id = payload["payload"]["message_id"]
        channel = payload["payload"]["channel"]

        try:
            event_timestamp_dt = parse_iso_datetime(event_timestamp)
            trace_id_uuid = UUID(trace_id)
        except ValueError as exc:
            raise NonRetriableError(
                f"invalid value: {exc}", reason="invalid_payload"
            ) from exc

        message_date_dt = None
        edit_date_dt = None
        forward_date_dt = None
        raw_text_value = None
        if event_type == "raw_message":
            try:
                message_date_dt = parse_iso_datetime(payload["payload"]["date"])
                edit_date_dt = parse_optional_iso_datetime(
                    payload["payload"].get("edit_date")
                )
                forward_date_dt = parse_optional_iso_datetime(
                    payload["payload"].get("forward_date")
                )
            except ValueError as exc:
                raise NonRetriableError(
                    f"invalid value: {exc}", reason="invalid_payload"
                ) from exc
            raw_text_value = payload["payload"].get("text")
        else:
            status = payload["payload"].get("status")
            if status == "error":
                raise NonRetriableError(
                    "persisted event status=error", reason="persisted_error"
                )

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

        # processed_events uses event_id as primary key, so prefix by consumer.
        processing_event_id = f"{self._config.consumer_id}:{event_id}"

        return MessageContext(
            event_id=event_id,
            processing_event_id=processing_event_id,
            event_type=event_type,
            event_timestamp=event_timestamp,
            event_timestamp_dt=event_timestamp_dt,
            trace_id=trace_id,
            trace_id_uuid=trace_id_uuid,
            message_id=message_id,
            channel=channel,
            message_date_dt=message_date_dt,
            edit_date_dt=edit_date_dt,
            forward_date_dt=forward_date_dt,
            raw_text=raw_text_value,
            payload=payload,
            key=key,
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
        )

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

                raw_message_id, raw_text = await self._resolve_raw_message(
                    conn, context
                )
                original_text = raw_text or ""
                language_start = time.monotonic()
                result = preprocess_text(
                    original_text,
                    language_min_confidence=self._config.language_detection.min_confidence,
                    full_analysis_languages=(
                        self._config.language_detection.full_analysis_languages
                    ),
                )
                if not self._config.language_detection.enabled:
                    result.is_supported_for_full_analysis = True
                    result.analysis_mode = "full"
                LANGUAGE_DETECTION_LATENCY.observe(time.monotonic() - language_start)
                MESSAGES_BY_LANGUAGE.labels(
                    language=result.original_language,
                    analysis_mode=result.analysis_mode,
                    supported_for_full_analysis=str(
                        result.is_supported_for_full_analysis
                    ).lower(),
                ).inc()
                logger.info(
                    "language detected event_id=%s language=%s confidence=%.3f "
                    "analysis_mode=%s full_supported=%s",
                    context.event_id,
                    result.original_language,
                    result.language_confidence,
                    result.analysis_mode,
                    result.is_supported_for_full_analysis,
                )
                processing_time_ms = (time.monotonic() - processing_started) * 1000.0

                row_id = await conn.fetchval(
                    INSERT_PREPROCESSED_SQL,
                    raw_message_id,
                    context.message_id,
                    context.channel,
                    context.event_id,
                    original_text,
                    result.cleaned_text,
                    result.normalized_text,
                    result.language,
                    result.original_language,
                    result.language_confidence,
                    result.is_supported_for_full_analysis,
                    result.analysis_mode,
                    result.translation_status,
                    result.tokens,
                    result.sentences_count,
                    result.word_count,
                    result.has_urls,
                    result.has_mentions,
                    result.has_hashtags,
                    result.urls,
                    result.mentions,
                    result.hashtags,
                    result.normalized_text_hash,
                    result.simhash64,
                    result.url_fingerprints,
                    result.primary_url_fingerprint,
                    self._config.preprocessing.version,
                    now_dt,
                    context.trace_id_uuid,
                    processing_time_ms,
                )
                status = "success" if row_id is not None else "duplicate"

        preprocessed_event = self._build_preprocessed_event(
            context, result, original_text, now_iso, processing_time_ms
        )
        try:
            self._preprocessed_validator.validate(preprocessed_event)
        except SchemaValidationError as exc:
            raise NonRetriableError(
                f"preprocessed schema validation failed: {exc}",
                reason="output_schema_invalid",
            ) from exc

        await self._producer.send_and_wait(
            self._config.kafka.output_topic,
            json.dumps(preprocessed_event).encode("utf-8"),
            key=context.event_id.encode("utf-8"),
        )

        async with self._pool.acquire() as conn:
            await conn.execute(UPDATE_PROCESSED_COMPLETED_SQL, context.processing_event_id)

        MESSAGES_PROCESSED.labels(status=status).inc()
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

    async def _resolve_raw_message(
        self, conn: asyncpg.Connection, context: MessageContext
    ) -> Tuple[str, Optional[str]]:
        if context.event_type == "persisted":
            row = await conn.fetchrow(
                SELECT_RAW_MESSAGE_SQL, context.channel, context.message_id
            )
            if row is None:
                raise MissingUpstreamError(
                    f"raw message missing channel={context.channel} message_id={context.message_id}"
                )
            return str(row["id"]), row["text"]

        row = await conn.fetchrow(
            SELECT_RAW_MESSAGE_SQL, context.channel, context.message_id
        )
        if row is not None:
            raw_text = row["text"] if row["text"] is not None else context.raw_text
            return str(row["id"]), raw_text

        if context.message_date_dt is None:
            raise NonRetriableError("raw message date missing", reason="invalid_payload")

        payload = context.payload["payload"]
        row = await conn.fetchrow(
            INSERT_RAW_MESSAGE_SQL,
            payload["message_id"],
            payload["channel"],
            payload.get("channel_id"),
            payload.get("permalink"),
            payload.get("text"),
            context.message_date_dt,
            payload.get("views", 0),
            payload.get("forwards", 0),
            self._json_value(payload.get("reactions")),
            self._json_value(payload.get("media")),
            payload.get("grouped_id"),
            context.edit_date_dt,
            payload.get("reply_to_message_id"),
            payload.get("reply_to_top_message_id"),
            payload.get("author") or payload.get("post_author"),
            payload.get("post_author") or payload.get("author"),
            payload.get("is_forwarded", False),
            payload.get("forward_from_channel"),
            payload.get("forward_from_channel_id"),
            payload.get("forward_from_message_id"),
            context.forward_date_dt,
            payload.get("forward_origin_type"),
            context.event_timestamp_dt,
            context.trace_id_uuid,
        )
        if row is not None:
            return str(row["id"]), payload.get("text")

        raw_message_id = await conn.fetchval(
            SELECT_RAW_MESSAGE_ID_SQL, context.channel, context.message_id
        )
        if raw_message_id is None:
            raise RuntimeError("raw_messages row not found after conflict")
        return str(raw_message_id), payload.get("text")

    def _build_preprocessed_event(
        self,
        context: MessageContext,
        result,
        original_text: str,
        now_iso: str,
        processing_time_ms: float,
    ) -> dict:
        return {
            "event_id": context.event_id,
            "event_type": "preprocessed",
            "event_timestamp": now_iso,
            "event_version": self._config.event_version,
            "source_system": self._config.source_system,
            "trace_id": context.trace_id,
            "payload": {
                "message_id": context.message_id,
                "channel": context.channel,
                "original_text": original_text,
                "cleaned_text": result.cleaned_text,
                "normalized_text": result.normalized_text,
                "language": result.language,
                "original_language": result.original_language,
                "language_confidence": result.language_confidence,
                "is_supported_for_full_analysis": (
                    result.is_supported_for_full_analysis
                ),
                "analysis_mode": result.analysis_mode,
                "translation_status": result.translation_status,
                "tokens": result.tokens,
                "sentences_count": result.sentences_count,
                "word_count": result.word_count,
                "has_urls": result.has_urls,
                "has_mentions": result.has_mentions,
                "has_hashtags": result.has_hashtags,
                "urls": result.urls,
                "mentions": result.mentions,
                "hashtags": result.hashtags,
                "preprocessing_metadata": {
                    "version": self._config.preprocessing.version,
                    "timestamp": now_iso,
                    "duration_ms": round(processing_time_ms, 3),
                },
            },
        }

    async def _update_processing_status(
        self, event_id: str, status: str, error_message: str
    ) -> None:
        if self._pool is None:
            return
        truncated = error_message[:1000]
        async with self._pool.acquire() as conn:
            await conn.execute(UPDATE_PROCESSED_STATUS_SQL, event_id, status, truncated)

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

    @staticmethod
    def _json_value(value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value
