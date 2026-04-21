from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import UUID

import asyncpg
import numpy as np
import torch
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from sentiment_analyzer.config import AppConfig
from sentiment_analyzer.metrics import (
    MESSAGES_CONSUMED,
    MESSAGES_DLQ,
    MESSAGES_PROCESSED,
    PROCESSING_LATENCY,
)
from sentiment_analyzer.schemas import JsonSchemaValidator, SchemaValidationError
from sentiment_analyzer.utils import decode_kafka_key, parse_iso_datetime, utc_now_iso


logger = logging.getLogger("sentiment_analyzer")

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

INSERT_SENTIMENT_RESULT_SQL = """
INSERT INTO sentiment_results (
    preprocessed_message_id,
    message_id,
    channel,
    event_id,
    sentiment_label,
    sentiment_score,
    positive_prob,
    negative_prob,
    neutral_prob,
    emotion_anger,
    emotion_fear,
    emotion_joy,
    emotion_sadness,
    emotion_surprise,
    emotion_disgust,
    aspects,
    model_name,
    model_version,
    model_framework,
    event_timestamp,
    trace_id,
    processing_time_ms,
    analyzed_at
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9,
    $10, $11, $12, $13, $14, $15, $16,
    $17, $18, $19, $20, $21, $22, $23
)
ON CONFLICT (channel, message_id) DO UPDATE
SET preprocessed_message_id = EXCLUDED.preprocessed_message_id,
    event_id = EXCLUDED.event_id,
    sentiment_label = EXCLUDED.sentiment_label,
    sentiment_score = EXCLUDED.sentiment_score,
    positive_prob = EXCLUDED.positive_prob,
    negative_prob = EXCLUDED.negative_prob,
    neutral_prob = EXCLUDED.neutral_prob,
    emotion_anger = EXCLUDED.emotion_anger,
    emotion_fear = EXCLUDED.emotion_fear,
    emotion_joy = EXCLUDED.emotion_joy,
    emotion_sadness = EXCLUDED.emotion_sadness,
    emotion_surprise = EXCLUDED.emotion_surprise,
    emotion_disgust = EXCLUDED.emotion_disgust,
    aspects = EXCLUDED.aspects,
    model_name = EXCLUDED.model_name,
    model_version = EXCLUDED.model_version,
    model_framework = EXCLUDED.model_framework,
    event_timestamp = EXCLUDED.event_timestamp,
    trace_id = EXCLUDED.trace_id,
    processing_time_ms = EXCLUDED.processing_time_ms,
    analyzed_at = EXCLUDED.analyzed_at
RETURNING id;
"""

LABEL_MAP = {
    "LABEL_0": "negative",
    "LABEL_1": "neutral",
    "LABEL_2": "positive",
    "NEGATIVE": "negative",
    "NEUTRAL": "neutral",
    "POSITIVE": "positive",
    "negative": "negative",
    "neutral": "neutral",
    "positive": "positive",
}


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


class SentimentAnalyzerService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._pool: Optional[asyncpg.Pool] = None
        self._health = HealthState()
        self._input_validator = JsonSchemaValidator(
            config.schemas.preprocessed_message_path
        )
        self._output_validator = JsonSchemaValidator(
            config.schemas.sentiment_enriched_path
        )
        self._stop_event = asyncio.Event()
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None

        self._model_lock = asyncio.Lock()
        self._device = self._resolve_device(config.model.device)
        self._tokenizer = None
        self._sentiment_model = None
        self._custom_label_map: Optional[dict[int, str]] = None
        logger.info("sentiment model configured device=%s", self._device.type)

    @staticmethod
    def _resolve_device(requested_device: str) -> torch.device:
        normalized = (requested_device or "auto").strip().lower()
        if normalized == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if normalized.startswith("cuda") and not torch.cuda.is_available():
            logger.warning(
                "cuda requested for sentiment model but unavailable, falling back to cpu"
            )
            return torch.device("cpu")
        return torch.device(normalized)

    def _load_model(self, config: AppConfig) -> str:
        local_path = config.model.local_path
        model_kwargs = {}
        if (
            self._device.type == "cuda"
            and config.model.use_float16
            and torch.cuda.is_available()
        ):
            model_kwargs["torch_dtype"] = torch.float16
        if config.model.cache_dir:
            model_kwargs["cache_dir"] = config.model.cache_dir

        if local_path and Path(local_path).exists():
            logger.info(
                "loading fine-tuned model from local_path=%s device=%s",
                local_path,
                self._device.type,
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                local_path,
                cache_dir=config.model.cache_dir,
            )
            self._sentiment_model = (
                AutoModelForSequenceClassification.from_pretrained(
                    local_path,
                    **model_kwargs,
                )
                .to(self._device)
            )
            self._sentiment_model.eval()
            self._custom_label_map = self._load_label_map(local_path, config)
            return f"local:{local_path}"

        logger.info(
            "loading pretrained model name=%s device=%s",
            config.model.name,
            self._device.type,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            config.model.name,
            cache_dir=config.model.cache_dir,
        )
        self._sentiment_model = (
            AutoModelForSequenceClassification.from_pretrained(
                config.model.name,
                **model_kwargs,
            )
            .to(self._device)
        )
        self._sentiment_model.eval()
        self._custom_label_map = None
        return f"hub:{config.model.name}"

    async def _ensure_model_loaded(self) -> None:
        if self._sentiment_model is not None and self._tokenizer is not None:
            return
        async with self._model_lock:
            if self._sentiment_model is not None and self._tokenizer is not None:
                return
            model_source = self._load_model(self._config)
            logger.info(
                "sentiment model loaded source=%s num_labels=%s",
                model_source,
                self._sentiment_model.config.num_labels,
            )

    @staticmethod
    def _load_label_map(
        model_dir: str, config: AppConfig
    ) -> Optional[dict[int, str]]:
        label2id_path = config.model.label2id_path
        if not label2id_path:
            label2id_path = str(Path(model_dir) / "label2id.json")
        id2label_path = str(
            Path(label2id_path).parent / "id2label.json"
        )
        p = Path(id2label_path)
        if p.exists():
            import json as _json

            raw = _json.loads(p.read_text(encoding="utf-8"))
            return {int(k): v for k, v in raw.items()}
        p2 = Path(label2id_path)
        if p2.exists():
            import json as _json

            raw = _json.loads(p2.read_text(encoding="utf-8"))
            return {v: k for k, v in raw.items()}
        return None

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
                        "skipping sentiment for event_id=%s language=%s analysis_mode=%s",
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

                result = await self._analyze_sentiment(context.original_text)
                processing_time_ms = (
                    time.monotonic() - processing_started
                ) * 1000.0

                await conn.fetchval(
                    INSERT_SENTIMENT_RESULT_SQL,
                    preprocessed_id,
                    context.message_id,
                    context.channel,
                    context.event_id,
                    result["label"],
                    result["score"],
                    result["positive_prob"],
                    result["negative_prob"],
                    result["neutral_prob"],
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    self._config.model.name,
                    self._config.model.version,
                    "transformers",
                    now_dt,
                    context.trace_id_uuid,
                    processing_time_ms,
                    now_dt,
                )

        enriched_event = self._build_enriched_event(
            context, result, now_iso, processing_time_ms
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

    # ── sentiment inference ─────────────────────────────────────────

    async def _analyze_sentiment(self, text: str) -> dict:
        await self._ensure_model_loaded()
        if not text or not text.strip():
            return {
                "label": "neutral",
                "score": 1.0,
                "positive_prob": 0.0,
                "negative_prob": 0.0,
                "neutral_prob": 1.0,
            }

        logits = self._aggregate_logits(text)
        probs = self._softmax(logits)
        pred_id = int(np.argmax(probs))

        if self._custom_label_map is not None:
            raw_label = self._custom_label_map.get(pred_id, str(pred_id))
        else:
            raw_label = self._sentiment_model.config.id2label.get(
                pred_id, str(pred_id)
            )
        label = self._normalize_label(raw_label)
        score = float(probs[pred_id])

        if score < self._config.model.neutral_threshold:
            label = "neutral"

        label_index = self._resolve_prob_indices()
        negative_prob = float(probs[label_index["negative"]]) if "negative" in label_index else 0.0
        neutral_prob = float(probs[label_index["neutral"]]) if "neutral" in label_index else 0.0
        positive_prob = float(probs[label_index["positive"]]) if "positive" in label_index else 0.0

        return {
            "label": label,
            "score": score,
            "positive_prob": positive_prob,
            "negative_prob": negative_prob,
            "neutral_prob": neutral_prob,
        }

    def _resolve_prob_indices(self) -> dict[str, int]:
        if self._custom_label_map is not None:
            idx: dict[str, int] = {}
            for int_id, raw_label in self._custom_label_map.items():
                normalized = self._normalize_label(raw_label)
                if normalized in ("negative", "neutral", "positive"):
                    idx[normalized] = int_id
            return idx
        return {"negative": 0, "neutral": 1, "positive": 2}

    def _aggregate_logits(self, text: str) -> np.ndarray:
        if self._tokenizer is None or self._sentiment_model is None:
            raise RuntimeError("sentiment model is not loaded")
        token_ids = self._tokenizer.encode(text, add_special_tokens=False)
        if not token_ids:
            return np.zeros(self._sentiment_model.config.num_labels, dtype=float)

        max_length = self._config.model.max_length
        chunk_overlap = self._config.model.chunk_overlap
        specials = self._tokenizer.num_special_tokens_to_add(pair=False)
        chunk_size = max(1, max_length - specials)
        overlap = min(chunk_overlap, max(0, chunk_size - 1))
        step = max(1, chunk_size - overlap)

        logits_list: list[np.ndarray] = []
        for start in range(0, len(token_ids), step):
            chunk = token_ids[start : start + chunk_size]
            input_ids = self._tokenizer.build_inputs_with_special_tokens(chunk)
            attention_mask = [1] * len(input_ids)
            inputs = {
                "input_ids": torch.tensor([input_ids], device=self._device),
                "attention_mask": torch.tensor(
                    [attention_mask], device=self._device
                ),
            }
            with torch.inference_mode():
                outputs = self._sentiment_model(**inputs)
            logits_list.append(outputs.logits.detach().cpu().numpy()[0])
            if start + chunk_size >= len(token_ids):
                break

        return np.mean(logits_list, axis=0)

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        exp = np.exp(logits - np.max(logits))
        return exp / exp.sum()

    @staticmethod
    def _normalize_label(raw_label: str) -> str:
        if raw_label in LABEL_MAP:
            return LABEL_MAP[raw_label]
        lower = raw_label.lower()
        if lower in LABEL_MAP:
            return LABEL_MAP[lower]
        return lower

    # ── output building ─────────────────────────────────────────────

    def _build_enriched_event(
        self,
        context: MessageContext,
        result: dict,
        now_iso: str,
        processing_time_ms: float,
    ) -> dict:
        return {
            "event_id": context.event_id,
            "event_type": "sentiment_enriched",
            "event_timestamp": now_iso,
            "event_version": self._config.event_version,
            "source_system": self._config.source_system,
            "trace_id": context.trace_id,
            "payload": {
                "message_id": context.message_id,
                "channel": context.channel,
                "sentiment": {
                    "label": result["label"],
                    "score": result["score"],
                    "positive_prob": result["positive_prob"],
                    "negative_prob": result["negative_prob"],
                    "neutral_prob": result["neutral_prob"],
                },
                "emotions": None,
                "model": {
                    "name": self._config.model.name,
                    "version": self._config.model.version,
                    "framework": "transformers",
                },
                "analyzed_at": now_iso,
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
