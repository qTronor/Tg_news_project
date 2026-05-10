from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import sqlite3
import asyncpg
import numpy as np
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from topic_clusterer.config import AppConfig
from topic_clusterer.embeddings_backend import build_embeddings_backend
from topic_clusterer.metrics import (
    BUFFER_SIZE,
    CLUSTERING_DURATION,
    CLUSTERING_RUNS,
    CLUSTERS_FOUND,
    MESSAGES_CONSUMED,
    MESSAGES_DLQ,
    MESSAGES_PROCESSED,
    PROCESSING_LATENCY,
)
from topic_clusterer.novelty import (
    NOVELTY_ALGO_VERSION,
    TopicSnapshot,
    calculate_topic_novelty,
    weighted_counts,
)
from topic_clusterer.pipeline import (
    Clusterer,
    CorpusItem,
    DimensionalityReducer,
    OutlierHandler,
    TopicMerger,
    TopicModelingPipeline,
    TopicRepresenter,
    config_hash,
)
from topic_clusterer.schemas import JsonSchemaValidator, SchemaValidationError
from topic_clusterer.utils import decode_kafka_key, parse_iso_datetime, utc_now_iso


logger = logging.getLogger("topic_clusterer")

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

SELECT_RAW_MESSAGE_DATE_SQL = """
SELECT message_date FROM raw_messages
WHERE channel = $1 AND message_id = $2;
"""

INSERT_CLUSTER_RUN_PG_SQL = """
INSERT INTO cluster_runs_pg (
    run_id,
    run_timestamp,
    algo_version,
    window_start,
    window_end,
    total_messages,
    total_clustered,
    total_noise,
    n_clusters,
    config_json,
    duration_seconds
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
ON CONFLICT (run_id) DO UPDATE
SET run_timestamp = EXCLUDED.run_timestamp,
    algo_version = EXCLUDED.algo_version,
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    total_messages = EXCLUDED.total_messages,
    total_clustered = EXCLUDED.total_clustered,
    total_noise = EXCLUDED.total_noise,
    n_clusters = EXCLUDED.n_clusters,
    config_json = EXCLUDED.config_json,
    duration_seconds = EXCLUDED.duration_seconds;
"""

INSERT_TOPIC_CLUSTER_METADATA_PG_SQL = """
INSERT INTO topic_cluster_metadata (
    public_cluster_id,
    run_id,
    cluster_id,
    centroid_json,
    keywords_json,
    representative_messages_json,
    top_entities_json,
    top_channels_json,
    time_distribution_json,
    confidence_score,
    stability_score,
    metadata_json
)
VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, $10, $11, $12::jsonb)
ON CONFLICT (public_cluster_id) DO UPDATE
SET centroid_json = EXCLUDED.centroid_json,
    keywords_json = EXCLUDED.keywords_json,
    representative_messages_json = EXCLUDED.representative_messages_json,
    top_entities_json = EXCLUDED.top_entities_json,
    top_channels_json = EXCLUDED.top_channels_json,
    time_distribution_json = EXCLUDED.time_distribution_json,
    confidence_score = EXCLUDED.confidence_score,
    stability_score = EXCLUDED.stability_score,
    metadata_json = EXCLUDED.metadata_json,
    created_at = NOW();
"""

UPSERT_TOPIC_HISTORY_SQL = """
INSERT INTO topic_history (
    public_cluster_id,
    run_id,
    cluster_id,
    first_seen,
    last_seen,
    message_count,
    channel_count,
    avg_sentiment,
    centroid_json,
    keywords_json,
    entities_json,
    channels_json,
    metadata_json,
    updated_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, NOW())
ON CONFLICT (public_cluster_id) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    cluster_id = EXCLUDED.cluster_id,
    first_seen = EXCLUDED.first_seen,
    last_seen = EXCLUDED.last_seen,
    message_count = EXCLUDED.message_count,
    channel_count = EXCLUDED.channel_count,
    avg_sentiment = EXCLUDED.avg_sentiment,
    centroid_json = EXCLUDED.centroid_json,
    keywords_json = EXCLUDED.keywords_json,
    entities_json = EXCLUDED.entities_json,
    channels_json = EXCLUDED.channels_json,
    metadata_json = EXCLUDED.metadata_json,
    updated_at = EXCLUDED.updated_at;
"""

INSERT_TOPIC_NOVELTY_SCORE_SQL = """
INSERT INTO topic_novelty_scores (
    public_cluster_id,
    run_id,
    novelty_score,
    novelty_status,
    nearest_topic_id,
    features_json,
    explanation_json,
    algorithm_version,
    calculated_at
)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, NOW());
"""

INSERT_TOPIC_LIFECYCLE_EVENT_SQL = """
INSERT INTO topic_lifecycle_events (
    public_cluster_id,
    run_id,
    event_type,
    event_time,
    related_topic_id,
    confidence,
    details_json
)
VALUES ($1, $2, $3, NOW(), $4, $5, $6::jsonb);
"""

UPSERT_TOPIC_SIMILARITY_LINK_SQL = """
INSERT INTO topic_similarity_links (
    source_cluster_id,
    target_cluster_id,
    run_id,
    semantic_similarity,
    entity_overlap,
    channel_overlap,
    keyword_overlap,
    overall_similarity,
    evidence_json,
    calculated_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
ON CONFLICT (source_cluster_id, target_cluster_id) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    semantic_similarity = EXCLUDED.semantic_similarity,
    entity_overlap = EXCLUDED.entity_overlap,
    channel_overlap = EXCLUDED.channel_overlap,
    keyword_overlap = EXCLUDED.keyword_overlap,
    overall_similarity = EXCLUDED.overall_similarity,
    evidence_json = EXCLUDED.evidence_json,
    calculated_at = EXCLUDED.calculated_at;
"""

SELECT_CLUSTER_ASSIGNMENT_REFS_SQL = """
SELECT
    rm.event_id,
    rm.id AS raw_message_id,
    pm.id AS preprocessed_message_id,
    rm.message_date,
    COALESCE(pm.trace_id, rm.trace_id) AS trace_id
FROM raw_messages rm
LEFT JOIN preprocessed_messages pm ON pm.event_id = rm.event_id
WHERE rm.event_id = ANY($1::varchar[]);
"""

INSERT_CLUSTER_ASSIGNMENT_PG_SQL = """
INSERT INTO cluster_assignments (
    run_id,
    cluster_id,
    event_id,
    channel,
    message_id,
    raw_message_id,
    preprocessed_message_id,
    cluster_probability,
    bucket_id,
    window_start,
    window_end,
    message_date
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
ON CONFLICT (run_id, event_id) DO UPDATE
SET cluster_id = EXCLUDED.cluster_id,
    channel = EXCLUDED.channel,
    message_id = EXCLUDED.message_id,
    raw_message_id = COALESCE(EXCLUDED.raw_message_id, cluster_assignments.raw_message_id),
    preprocessed_message_id = COALESCE(EXCLUDED.preprocessed_message_id, cluster_assignments.preprocessed_message_id),
    cluster_probability = EXCLUDED.cluster_probability,
    bucket_id = EXCLUDED.bucket_id,
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    message_date = COALESCE(EXCLUDED.message_date, cluster_assignments.message_date);
"""

SQLITE_INIT_SQL = """
CREATE TABLE IF NOT EXISTS message_embeddings (
    event_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    text TEXT,
    language TEXT,
    analysis_mode TEXT,
    embedding TEXT,
    trace_id TEXT,
    event_timestamp TEXT NOT NULL,
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP,
    clustered INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cluster_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    cluster_probability REAL NOT NULL,
    bucket_id TEXT,
    run_id TEXT NOT NULL,
    run_timestamp TEXT NOT NULL,
    algo_version TEXT NOT NULL,
    window_start TEXT,
    window_end TEXT
);

CREATE TABLE IF NOT EXISTS cluster_runs (
    run_id TEXT PRIMARY KEY,
    run_timestamp TEXT NOT NULL,
    algo_version TEXT NOT NULL,
    window_start TEXT,
    window_end TEXT,
    total_messages INTEGER,
    total_clustered INTEGER,
    total_noise INTEGER,
    n_clusters INTEGER,
    config_json TEXT,
    duration_seconds REAL
);
"""

SQLITE_SCHEMA_PATCHES = [
    "ALTER TABLE message_embeddings ADD COLUMN trace_id TEXT",
    "ALTER TABLE message_embeddings ADD COLUMN language TEXT",
    "ALTER TABLE message_embeddings ADD COLUMN analysis_mode TEXT",
]


class ProcessingOutcome(Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    DLQ = "dlq"
    RETRY_PENDING = "retry_pending"


class NonRetriableError(Exception):
    def __init__(self, message: str, reason: str = "invalid_payload") -> None:
        super().__init__(message)
        self.reason = reason


def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    db_connected: bool = False
    last_processed_at: Optional[str] = None
    last_clustering_at: Optional[str] = None
    last_error: Optional[str] = None


@dataclass
class ClusteringRunBatch:
    run_id: str
    run_timestamp: datetime
    algo_version: str
    window_start: Optional[datetime]
    window_end: Optional[datetime]
    total_messages: int
    total_clustered: int
    total_noise: int
    n_clusters: int
    config_json: dict[str, Any]
    duration_seconds: float
    assignments: list[dict[str, Any]]
    topic_metadata: dict[int, Any]


class TopicClustererService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._pool: Optional[asyncpg.Pool] = None
        self._db: Optional[sqlite3.Connection] = None
        self._health = HealthState()
        self._input_validator = JsonSchemaValidator(
            config.schemas.preprocessed_message_path
        )
        self._output_validator = JsonSchemaValidator(
            config.schemas.topic_assignment_path
        )
        self._stop_event = asyncio.Event()
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None
        self._clustering_task: Optional[asyncio.Task] = None
        self._clustering_lock = asyncio.Lock()
        self._embeddings_backend = build_embeddings_backend(config)
        logger.info(
            "topic model configured name=%s backend=%s",
            self._embedding_model_name(),
            config.model.backend,
        )

    async def _ensure_model_loaded(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._embeddings_backend.ensure_loaded)

    def _embedding_model_name(self) -> str:
        selected = self._config.model.embedding_model or self._config.model.sbert_model
        return self._config.model.embedding_models.get(selected, selected)

    async def start(self) -> None:
        await self._start_db()
        self._start_embeddings_db()
        await self._start_kafka()
        await self._start_http()
        self._health.ready = True
        self._clustering_task = asyncio.create_task(self._clustering_scheduler())
        logger.info("service started")

    async def stop(self) -> None:
        self._health.ready = False
        if self._clustering_task is not None:
            self._clustering_task.cancel()
            try:
                await self._clustering_task
            except asyncio.CancelledError:
                pass
        if self._consumer is not None:
            await self._consumer.stop()
        if self._producer is not None:
            await self._producer.stop()
        if self._pool is not None:
            await self._pool.close()
        if self._db is not None:
            self._db.close()
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

    def _start_embeddings_db(self) -> None:
        db_path = Path(self._config.storage.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        for statement in SQLITE_INIT_SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                self._db.execute(statement)
        for statement in SQLITE_SCHEMA_PATCHES:
            try:
                self._db.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        self._health.db_connected = True
        logger.info("embeddings db initialized path=%s", db_path)

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
            "db_connected": self._health.db_connected,
            "last_processed_at": self._health.last_processed_at,
            "last_clustering_at": self._health.last_clustering_at,
            "last_error": self._health.last_error,
        }
        return web.json_response(payload)

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        return web.Response(
            body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    # ── record handling (online ingest) ─────────────────────────────

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

        for attempt in range(1, self._config.retry.max_attempts + 1):
            try:
                outcome = await self._ingest_once(context)
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
        original_text = (
            payload["payload"].get("normalized_text")
            or payload["payload"].get("cleaned_text")
            or payload["payload"].get("original_text", "")
        )
        original_language = payload["payload"].get(
            "original_language",
            payload["payload"].get("language", "und"),
        )
        analysis_mode = payload["payload"].get("analysis_mode", "full")

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
            payload=payload,
            key=key,
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
        )

    # ── online ingest: compute embedding + store in embeddings DB ───

    async def _ingest_once(self, context: MessageContext) -> ProcessingOutcome:
        if self._pool is None or self._db is None:
            raise RuntimeError("service not initialized")

        message_date_dt: Optional[datetime] = None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                should_process = await self._begin_processing(conn, context)
                if not should_process:
                    logger.info("duplicate event_id=%s", context.event_id)
                    MESSAGES_PROCESSED.labels(status="duplicate").inc()
                    return ProcessingOutcome.DUPLICATE
                message_date_dt = await conn.fetchval(
                    SELECT_RAW_MESSAGE_DATE_SQL,
                    context.channel,
                    context.message_id,
                )

        text = context.original_text
        if not text or not text.strip():
            MESSAGES_PROCESSED.labels(status="skipped_empty").inc()
            async with self._pool.acquire() as conn:
                await conn.execute(
                    UPDATE_PROCESSED_COMPLETED_SQL, context.processing_event_id
                )
            return ProcessingOutcome.SUCCESS

        embedding = await self._compute_embedding(text)

        self._db.execute(
            """
            INSERT INTO message_embeddings
                (event_id, channel, message_id, text, language, analysis_mode,
                 embedding, trace_id, event_timestamp, clustered)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                (SELECT clustered FROM message_embeddings WHERE event_id = ?),
                0
            ))
            ON CONFLICT(event_id) DO UPDATE SET
                channel = excluded.channel,
                message_id = excluded.message_id,
                text = excluded.text,
                language = excluded.language,
                analysis_mode = excluded.analysis_mode,
                embedding = excluded.embedding,
                trace_id = excluded.trace_id,
                event_timestamp = excluded.event_timestamp,
                clustered = message_embeddings.clustered
            """,
            [
                context.event_id,
                context.channel,
                context.message_id,
                text[:2000],
                context.original_language,
                context.analysis_mode,
                json.dumps(embedding.tolist()),
                context.trace_id,
                (message_date_dt or context.event_timestamp_dt).isoformat(),
                context.event_id,
            ],
        )
        self._db.commit()

        unclustered = self._db.execute(
            "SELECT count(*) FROM message_embeddings WHERE clustered = 0"
        ).fetchone()[0]
        BUFFER_SIZE.set(unclustered)

        async with self._pool.acquire() as conn:
            await conn.execute(
                UPDATE_PROCESSED_COMPLETED_SQL, context.processing_event_id
            )

        if unclustered >= self._config.clustering.trigger_min_messages:
            try:
                await self._run_clustering_cycle()
            except Exception:  # noqa: BLE001 - clustering retries via scheduler
                logger.exception(
                    "immediate clustering trigger failed event_id=%s",
                    context.event_id,
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

    async def _compute_embedding(self, text: str) -> np.ndarray:
        await self._ensure_model_loaded()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._embeddings_backend.compute(
                text,
                normalize=self._config.model.normalize_embeddings,
                batch_size=self._config.model.batch_size,
            ),
        )

    # ── clustering scheduler ────────────────────────────────────────

    async def _clustering_scheduler(self) -> None:
        interval = self._config.clustering.scheduler_interval_seconds
        logger.info("clustering scheduler started interval=%ss", interval)
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(interval)
                if self._stop_event.is_set():
                    break
                await self._run_clustering_cycle()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 - scheduler must not crash
                logger.exception("clustering run failed")
                CLUSTERING_RUNS.labels(status="error").inc()

    async def _run_clustering_cycle(self) -> None:
        if self._clustering_lock.locked():
            return
        async with self._clustering_lock:
            loop = asyncio.get_running_loop()
            while not self._stop_event.is_set():
                batch = await loop.run_in_executor(None, self._build_clustering_run)
                if batch is None:
                    break
                await self._persist_clustering_run_pg(batch)
                await self._publish_assignment_events(batch)
                await self._publish_novelty_events(batch)
                await loop.run_in_executor(
                    None, self._record_clustering_run_sqlite, batch
                )

    def _build_clustering_run(self) -> Optional[ClusteringRunBatch]:
        if self._db is None:
            return None

        rows = self._db.execute(
            "SELECT event_id, channel, message_id, text, embedding, trace_id, event_timestamp, language, analysis_mode "
            "FROM message_embeddings WHERE clustered = 0 "
            "ORDER BY event_timestamp"
        ).fetchall()

        if not rows:
            return None

        logger.info("starting clustering run messages=%s", len(rows))
        start_time = time.monotonic()

        event_ids = [r[0] for r in rows]
        channels = [r[1] for r in rows]
        message_ids = [r[2] for r in rows]
        trace_ids = [r[5] for r in rows]
        raw_timestamps = [r[6] for r in rows]
        languages = [r[7] for r in rows]
        analysis_modes = [r[8] for r in rows]
        timestamps = [
            parse_iso_datetime(ts) if isinstance(ts, str) else ts
            for ts in raw_timestamps
        ]
        embeddings = np.array(
            [json.loads(r[4] or "[]") for r in rows], dtype=np.float32
        )

        window_hours = self._config.clustering.window_hours
        bucket_ids = self._make_time_buckets(timestamps, window_hours)
        labels, probs, strategy, topic_metadata, metrics = self._cluster_by_bucket(
            embeddings,
            bucket_ids,
            event_ids,
            channels,
            message_ids,
            [r[3] for r in rows],
            timestamps,
        )

        now_dt = datetime.now(timezone.utc)
        algo_version = f"{strategy}_v{self._config.model.version}"
        run_id = self._make_run_id(event_ids, algo_version)
        duration = time.monotonic() - start_time

        n_clusters = len(set(labels)) - (1 if -1 in set(labels) else 0)
        n_clustered = int((labels >= 0).sum())
        n_noise = int((labels == -1).sum())
        window_start = min(timestamps) if timestamps else None
        window_end = max(timestamps) if timestamps else None
        dataset_version = self._config.clustering.dataset_version
        if dataset_version is None and window_start is not None and window_end is not None:
            dataset_version = f"{window_start.date()}_{window_end.date()}"
        config_json = {
            "min_cluster_size": self._config.clustering.min_cluster_size,
            "min_samples": self._config.clustering.min_samples,
            "trigger_min_messages": self._config.clustering.trigger_min_messages,
            "n_neighbors": self._config.clustering.n_neighbors,
            "min_dist": self._config.clustering.min_dist,
            "n_components": self._config.clustering.n_components
            or self._config.clustering.umap_n_components,
            "umap_n_components": self._config.clustering.umap_n_components,
            "top_n_words": self._config.clustering.top_n_words,
            "ngram_range": list(self._config.clustering.ngram_range),
            "nr_topics": self._config.clustering.nr_topics,
            "min_topic_size": self._config.clustering.min_topic_size,
            "seed": self._config.clustering.seed,
            "window_hours": window_hours,
            "strategy": strategy,
            "model_version": self._config.model.version,
            "embedding_model": self._embedding_model_name(),
            "dataset_version": dataset_version,
            "multilingual": True,
            "languages": sorted({lang for lang in languages if lang}),
            "analysis_modes": sorted({mode for mode in analysis_modes if mode}),
        }
        config_json["config_hash"] = config_hash(config_json)
        config_json["metrics"] = metrics

        assignments: list[dict[str, Any]] = []
        for i, event_id in enumerate(event_ids):
            assignments.append(
                {
                    "event_id": event_id,
                    "channel": channels[i],
                    "message_id": message_ids[i],
                    "cluster_id": int(labels[i]),
                    "cluster_probability": float(probs[i]),
                    "bucket_id": bucket_ids[i],
                    "message_date": timestamps[i],
                    "trace_id": trace_ids[i],
                }
            )

        return ClusteringRunBatch(
            run_id=run_id,
            run_timestamp=now_dt,
            algo_version=algo_version,
            window_start=window_start,
            window_end=window_end,
            total_messages=len(rows),
            total_clustered=n_clustered,
            total_noise=n_noise,
            n_clusters=n_clusters,
            config_json=config_json,
            duration_seconds=duration,
            assignments=assignments,
            topic_metadata=topic_metadata,
        )

    @staticmethod
    def _make_run_id(event_ids: list[str], algo_version: str) -> str:
        digest = hashlib.sha1(
            f"{algo_version}|{'|'.join(sorted(event_ids))}".encode("utf-8")
        ).hexdigest()[:12]
        return f"run_{digest}"

    async def _persist_clustering_run_pg(self, batch: ClusteringRunBatch) -> None:
        if self._pool is None:
            raise RuntimeError("postgres pool not initialized")

        event_ids = [assignment["event_id"] for assignment in batch.assignments]
        async with self._pool.acquire() as conn:
            has_run_metadata_columns = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'cluster_runs_pg'
                      AND column_name = 'config_hash'
                );
                """
            )
            has_topic_metadata_table = await conn.fetchval(
                "SELECT to_regclass('public.topic_cluster_metadata') IS NOT NULL;"
            )
            has_topic_novelty_tables = await conn.fetchval(
                "SELECT to_regclass('public.topic_novelty_scores') IS NOT NULL;"
            )
            async with conn.transaction():
                await conn.execute(
                    INSERT_CLUSTER_RUN_PG_SQL,
                    batch.run_id,
                    batch.run_timestamp,
                    batch.algo_version,
                    batch.window_start,
                    batch.window_end,
                    batch.total_messages,
                    batch.total_clustered,
                    batch.total_noise,
                    batch.n_clusters,
                    json.dumps(batch.config_json),
                    batch.duration_seconds,
                )
                if has_run_metadata_columns:
                    await conn.execute(
                        """
                        UPDATE cluster_runs_pg
                        SET model_version = $2,
                            config_hash = $3,
                            dataset_version = $4,
                            embedding_model = $5,
                            metrics_json = $6::jsonb
                        WHERE run_id = $1;
                        """,
                        batch.run_id,
                        batch.config_json.get("model_version"),
                        batch.config_json.get("config_hash"),
                        batch.config_json.get("dataset_version"),
                        batch.config_json.get("embedding_model"),
                        json.dumps(batch.config_json.get("metrics", {})),
                    )
                else:
                    logger.warning(
                        "cluster_runs_pg BERTopic metadata columns are not migrated; keeping data in config_json"
                    )

                refs_rows = await conn.fetch(SELECT_CLUSTER_ASSIGNMENT_REFS_SQL, event_ids)
                refs = {row["event_id"]: row for row in refs_rows}

                for assignment in batch.assignments:
                    ref = refs.get(assignment["event_id"])
                    if ref is not None and assignment.get("trace_id") in (None, ""):
                        trace_id = ref["trace_id"]
                        assignment["trace_id"] = str(trace_id) if trace_id is not None else None

                await conn.executemany(
                    INSERT_CLUSTER_ASSIGNMENT_PG_SQL,
                    [
                        (
                            batch.run_id,
                            assignment["cluster_id"],
                            assignment["event_id"],
                            assignment["channel"],
                            assignment["message_id"],
                            refs[assignment["event_id"]]["raw_message_id"]
                            if assignment["event_id"] in refs
                            else None,
                            refs[assignment["event_id"]]["preprocessed_message_id"]
                            if assignment["event_id"] in refs
                            else None,
                            assignment["cluster_probability"],
                            assignment["bucket_id"],
                            batch.window_start,
                            batch.window_end,
                            refs[assignment["event_id"]]["message_date"]
                            if assignment["event_id"] in refs
                            else None
                            or assignment["message_date"],
                        )
                        for assignment in batch.assignments
                    ],
                )
                if has_topic_metadata_table:
                    await self._persist_topic_metadata_pg(conn, batch)
                else:
                    logger.warning(
                        "topic_cluster_metadata table is not migrated; skipping explainability metadata"
                    )
                if has_topic_metadata_table and has_topic_novelty_tables:
                    await self._score_topic_novelty_pg(conn, batch)
                elif not has_topic_novelty_tables:
                    logger.warning(
                        "topic novelty tables are not migrated; skipping novelty scoring"
                    )

    async def _persist_topic_metadata_pg(
        self,
        conn: asyncpg.Connection,
        batch: ClusteringRunBatch,
    ) -> None:
        assignments_by_cluster: dict[int, list[dict[str, Any]]] = {}
        for assignment in batch.assignments:
            if assignment["cluster_id"] >= 0:
                assignments_by_cluster.setdefault(assignment["cluster_id"], []).append(assignment)
        top_entities_by_cluster = await self._load_top_entities_for_run(conn, batch.run_id)

        for cluster_id, topic_meta in batch.topic_metadata.items():
            public_cluster_id = f"{batch.run_id}:{cluster_id}"
            metadata_json = {
                "model_version": self._config.model.version,
                "config_hash": batch.config_json.get("config_hash"),
                "dataset_version": batch.config_json.get("dataset_version"),
                "embedding_model": batch.config_json.get("embedding_model"),
                "metrics": batch.config_json.get("metrics", {}),
                "run_id": batch.run_id,
                "created_at": batch.run_timestamp.isoformat(),
                "message_count": len(assignments_by_cluster.get(cluster_id, [])),
                "config": batch.config_json,
            }
            await conn.execute(
                INSERT_TOPIC_CLUSTER_METADATA_PG_SQL,
                public_cluster_id,
                batch.run_id,
                cluster_id,
                json.dumps(topic_meta.centroid),
                json.dumps(topic_meta.keywords, ensure_ascii=False),
                json.dumps(topic_meta.representative_messages, ensure_ascii=False),
                json.dumps(top_entities_by_cluster.get(cluster_id, []), ensure_ascii=False),
                json.dumps(topic_meta.top_channels, ensure_ascii=False),
                json.dumps(topic_meta.time_distribution, ensure_ascii=False),
                topic_meta.confidence_score,
                topic_meta.stability_score,
                json.dumps(metadata_json, ensure_ascii=False),
            )

    async def _load_top_entities_for_run(
        self,
        conn: asyncpg.Connection,
        run_id: str,
    ) -> dict[int, list[dict[str, Any]]]:
        try:
            rows = await conn.fetch(
                """
                SELECT
                    ca.cluster_id,
                    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
                    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
                    nr.entity_type,
                    count(*) AS mention_count
                FROM cluster_assignments ca
                JOIN ner_results nr ON nr.event_id = ca.event_id
                WHERE ca.run_id = $1
                  AND ca.cluster_id >= 0
                GROUP BY
                    ca.cluster_id,
                    lower(COALESCE(nr.normalized_text, nr.entity_text)),
                    nr.entity_type
                ORDER BY ca.cluster_id, mention_count DESC, entity_text ASC;
                """,
                run_id,
            )
        except (
            asyncpg.exceptions.UndefinedTableError,
            asyncpg.exceptions.UndefinedColumnError,
        ):
            return {}

        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            cluster_id = int(row["cluster_id"])
            if len(grouped.setdefault(cluster_id, [])) >= 10:
                continue
            grouped[cluster_id].append(
                {
                    "id": f"{row['entity_type']}:{row['entity_key']}",
                    "text": row["entity_text"],
                    "type": row["entity_type"],
                    "mention_count": int(row["mention_count"] or 0),
                }
            )
        return grouped

    async def _score_topic_novelty_pg(
        self,
        conn: asyncpg.Connection,
        batch: ClusteringRunBatch,
    ) -> None:
        stats_rows = await conn.fetch(
            """
            SELECT
                ca.cluster_id,
                ca.public_cluster_id,
                min(rm.message_date) AS first_seen,
                max(rm.message_date) AS last_seen,
                count(*) AS message_count,
                count(DISTINCT rm.channel) AS channel_count,
                COALESCE(avg(
                    CASE
                        WHEN sr.positive_prob IS NOT NULL OR sr.negative_prob IS NOT NULL
                            THEN COALESCE(sr.positive_prob, 0) - COALESCE(sr.negative_prob, 0)
                        WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'positive'
                            THEN COALESCE(sr.sentiment_score, 0)
                        WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'negative'
                            THEN -COALESCE(sr.sentiment_score, 0)
                        ELSE 0
                    END
                ), 0) AS avg_sentiment
            FROM cluster_assignments ca
            JOIN raw_messages rm ON rm.event_id = ca.event_id
            LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
            WHERE ca.run_id = $1
              AND ca.cluster_id >= 0
            GROUP BY ca.cluster_id, ca.public_cluster_id;
            """,
            batch.run_id,
        )
        stats_by_cluster = {int(row["cluster_id"]): row for row in stats_rows}
        top_entities_by_cluster = await self._load_top_entities_for_run(conn, batch.run_id)
        history_rows = await conn.fetch(
            """
            SELECT
                public_cluster_id,
                run_id,
                cluster_id,
                first_seen,
                last_seen,
                message_count,
                avg_sentiment,
                centroid_json,
                keywords_json,
                entities_json,
                channels_json
            FROM topic_history
            WHERE run_id <> $1
            ORDER BY last_seen DESC NULLS LAST
            LIMIT 500;
            """,
            batch.run_id,
        )
        history = [self._snapshot_from_history_row(row) for row in history_rows]

        for cluster_id, topic_meta in batch.topic_metadata.items():
            stat = stats_by_cluster.get(cluster_id)
            if stat is None:
                continue
            public_cluster_id = stat["public_cluster_id"]
            current = TopicSnapshot(
                public_cluster_id=public_cluster_id,
                run_id=batch.run_id,
                cluster_id=cluster_id,
                centroid=list(topic_meta.centroid or []),
                keywords=list(topic_meta.keywords or []),
                entities=weighted_counts(
                    top_entities_by_cluster.get(cluster_id, []),
                    "id",
                    "mention_count",
                ),
                channels=weighted_counts(list(topic_meta.top_channels or []), "channel", "count"),
                message_count=int(stat["message_count"] or 0),
                first_seen=stat["first_seen"],
                last_seen=stat["last_seen"],
                avg_sentiment=float(stat["avg_sentiment"] or 0),
            )
            await conn.execute(
                UPSERT_TOPIC_HISTORY_SQL,
                current.public_cluster_id,
                current.run_id,
                current.cluster_id,
                current.first_seen,
                current.last_seen,
                current.message_count,
                int(stat["channel_count"] or 0),
                current.avg_sentiment,
                json.dumps(current.centroid),
                json.dumps(current.keywords, ensure_ascii=False),
                json.dumps(current.entities, ensure_ascii=False),
                json.dumps(current.channels, ensure_ascii=False),
                json.dumps(
                    {
                        "model_version": self._config.model.version,
                        "embedding_model": batch.config_json.get("embedding_model"),
                        "config_hash": batch.config_json.get("config_hash"),
                    },
                    ensure_ascii=False,
                ),
            )
            result = calculate_topic_novelty(current, history)
            await conn.execute(
                INSERT_TOPIC_NOVELTY_SCORE_SQL,
                result.public_cluster_id,
                current.run_id,
                result.novelty_score,
                result.status,
                result.nearest_topic_id,
                json.dumps(result.features, ensure_ascii=False),
                json.dumps(result.explanation, ensure_ascii=False),
                NOVELTY_ALGO_VERSION,
            )
            await conn.execute(
                INSERT_TOPIC_LIFECYCLE_EVENT_SQL,
                result.public_cluster_id,
                current.run_id,
                result.status,
                result.nearest_topic_id,
                result.novelty_score,
                json.dumps(
                    {
                        "features": result.features,
                        "explanation": result.explanation,
                    },
                    ensure_ascii=False,
                ),
            )
            for link in result.similarity_links:
                await conn.execute(
                    UPSERT_TOPIC_SIMILARITY_LINK_SQL,
                    result.public_cluster_id,
                    link["topic_id"],
                    current.run_id,
                    link["semantic_similarity"],
                    link["entity_overlap"],
                    link["channel_overlap"],
                    link["keyword_overlap"],
                    link["overall_similarity"],
                    json.dumps(link, ensure_ascii=False),
                )
            logger.info(
                "topic novelty scored cluster=%s score=%.3f status=%s nearest=%s",
                result.public_cluster_id,
                result.novelty_score,
                result.status,
                result.nearest_topic_id,
            )

    def _snapshot_from_history_row(self, row: asyncpg.Record) -> TopicSnapshot:
        return TopicSnapshot(
            public_cluster_id=row["public_cluster_id"],
            run_id=row["run_id"],
            cluster_id=int(row["cluster_id"]),
            centroid=self._json_list(row["centroid_json"]),
            keywords=[str(item) for item in self._json_list(row["keywords_json"])],
            entities=self._json_float_dict(row["entities_json"]),
            channels=self._json_float_dict(row["channels_json"]),
            message_count=int(row["message_count"] or 0),
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            avg_sentiment=float(row["avg_sentiment"] or 0),
        )

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        return value if isinstance(value, list) else []

    @staticmethod
    def _json_float_dict(value: Any) -> dict[str, float]:
        if value is None:
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return {}
        if not isinstance(value, dict):
            return {}
        result: dict[str, float] = {}
        for key, raw in value.items():
            try:
                result[str(key)] = float(raw)
            except (TypeError, ValueError):
                continue
        return result

    async def _publish_assignment_events(self, batch: ClusteringRunBatch) -> None:
        if self._producer is None:
            raise RuntimeError("kafka producer not initialized")

        for assignment in batch.assignments:
            event = self._build_topic_assignment_event(batch, assignment)
            self._output_validator.validate(event)
            await self._producer.send_and_wait(
                self._config.kafka.output_topic,
                json.dumps(event).encode("utf-8"),
                key=assignment["event_id"].encode("utf-8"),
            )

    async def _publish_novelty_events(self, batch: ClusteringRunBatch) -> None:
        if self._producer is None or self._pool is None:
            return
        async with self._pool.acquire() as conn:
            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        public_cluster_id,
                        novelty_score,
                        novelty_status,
                        nearest_topic_id,
                        features_json,
                        explanation_json,
                        calculated_at
                    FROM topic_novelty_scores_latest
                    WHERE run_id = $1
                      AND novelty_status = 'new'
                    ORDER BY novelty_score DESC;
                    """,
                    batch.run_id,
                )
            except (
                asyncpg.exceptions.UndefinedTableError,
                asyncpg.exceptions.UndefinedColumnError,
            ):
                return
        for row in rows:
            payload = {
                "event_id": f"topic_novelty:{row['public_cluster_id']}",
                "event_type": "topic_novelty_detected",
                "event_timestamp": _dt_iso(row["calculated_at"]),
                "event_version": self._config.event_version,
                "source_system": self._config.source_system,
                "payload": {
                    "public_cluster_id": row["public_cluster_id"],
                    "run_id": batch.run_id,
                    "novelty_score": float(row["novelty_score"] or 0),
                    "novelty_status": row["novelty_status"],
                    "nearest_topic_id": row["nearest_topic_id"],
                    "features": row["features_json"] or {},
                    "explanation": row["explanation_json"] or {},
                },
            }
            await self._producer.send_and_wait(
                "topic.novelty.candidates",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                key=str(row["public_cluster_id"]).encode("utf-8"),
            )

    def _build_topic_assignment_event(
        self,
        batch: ClusteringRunBatch,
        assignment: dict[str, Any],
    ) -> dict[str, Any]:
        public_cluster_id = f"{batch.run_id}:{assignment['cluster_id']}"
        assigned_at = batch.run_timestamp.isoformat().replace("+00:00", "Z")
        window_start = (
            batch.window_start.isoformat().replace("+00:00", "Z")
            if batch.window_start is not None
            else None
        )
        window_end = (
            batch.window_end.isoformat().replace("+00:00", "Z")
            if batch.window_end is not None
            else None
        )
        return {
            "event_id": assignment["event_id"],
            "event_type": "topic_assignment",
            "event_timestamp": assigned_at,
            "event_version": self._config.event_version,
            "source_system": self._config.source_system,
            "trace_id": str(assignment["trace_id"]),
            "payload": {
                "message_id": assignment["message_id"],
                "channel": assignment["channel"],
                "topic_id": public_cluster_id,
                "public_cluster_id": public_cluster_id,
                "cluster_id": assignment["cluster_id"],
                "run_id": batch.run_id,
                "bucket_id": assignment["bucket_id"],
                "cluster_probability": round(
                    float(assignment["cluster_probability"]), 6
                ),
                "model": {
                    "name": self._embedding_model_name(),
                    "version": self._config.model.version,
                    "framework": "sentence-transformers",
                },
                "clustering": {
                    "algorithm": batch.algo_version,
                    "window_start": window_start,
                    "window_end": window_end,
                },
                "assigned_at": assigned_at,
            },
        }

    def _record_clustering_run_sqlite(self, batch: ClusteringRunBatch) -> None:
        if self._db is None:
            return

        def _ts(val: Optional[datetime]) -> Optional[str]:
            return val.isoformat() if val is not None else None

        self._db.execute("DELETE FROM cluster_results WHERE run_id = ?", [batch.run_id])
        self._db.execute("DELETE FROM cluster_runs WHERE run_id = ?", [batch.run_id])

        self._db.execute(
            "INSERT INTO cluster_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                batch.run_id,
                batch.run_timestamp.isoformat(),
                batch.algo_version,
                _ts(batch.window_start),
                _ts(batch.window_end),
                batch.total_messages,
                batch.total_clustered,
                batch.total_noise,
                batch.n_clusters,
                json.dumps(batch.config_json),
                batch.duration_seconds,
            ],
        )

        for assignment in batch.assignments:
            self._db.execute(
                "INSERT INTO cluster_results "
                "(event_id, channel, message_id, cluster_id, cluster_probability, "
                "bucket_id, run_id, run_timestamp, algo_version, window_start, window_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    assignment["event_id"],
                    assignment["channel"],
                    assignment["message_id"],
                    assignment["cluster_id"],
                    assignment["cluster_probability"],
                    assignment["bucket_id"],
                    batch.run_id,
                    batch.run_timestamp.isoformat(),
                    batch.algo_version,
                    _ts(batch.window_start),
                    _ts(batch.window_end),
                ],
            )

        placeholders = ",".join("?" * len(batch.assignments))
        self._db.execute(
            f"UPDATE message_embeddings SET clustered = 1 WHERE event_id IN ({placeholders})",
            [assignment["event_id"] for assignment in batch.assignments],
        )
        self._db.commit()
        remaining = self._db.execute(
            "SELECT count(*) FROM message_embeddings WHERE clustered = 0"
        ).fetchone()[0]
        BUFFER_SIZE.set(remaining)

        self._export_parquet(batch.run_id)

        CLUSTERING_RUNS.labels(status="success").inc()
        CLUSTERING_DURATION.observe(batch.duration_seconds)
        CLUSTERS_FOUND.set(batch.n_clusters)
        self._health.last_clustering_at = utc_now_iso()

        logger.info(
            "clustering complete run_id=%s n_clusters=%s clustered=%s noise=%s duration=%.1fs",
            batch.run_id,
            batch.n_clusters,
            batch.total_clustered,
            batch.total_noise,
            batch.duration_seconds,
        )

    def _make_time_buckets(
        self, timestamps: list, window_hours: int
    ) -> list[str]:
        buckets: list[str] = []
        for ts in timestamps:
            if ts is None:
                buckets.append("unknown")
                continue
            if isinstance(ts, str):
                ts = parse_iso_datetime(ts)
            hour_floor = ts.hour - (ts.hour % window_hours)
            bucketed = ts.replace(hour=hour_floor, minute=0, second=0, microsecond=0)
            buckets.append(str(bucketed))
        return buckets

    def _cluster_by_bucket(
        self,
        embeddings: np.ndarray,
        bucket_ids: list[str],
        event_ids: list[str],
        channels: list[str],
        message_ids: list[int],
        texts: list[str],
        timestamps: list[datetime],
    ) -> tuple[np.ndarray, np.ndarray, str, dict[int, Any], dict[str, Any]]:
        labels = np.full(len(embeddings), -1, dtype=int)
        probs = np.zeros(len(embeddings), dtype=float)
        strategy = "umap_hdbscan"
        metadata: dict[int, Any] = {}
        metric_parts: list[dict[str, Any]] = []

        unique_buckets: dict[str, list[int]] = {}
        for i, bid in enumerate(bucket_ids):
            unique_buckets.setdefault(bid, []).append(i)

        cluster_offset = 0
        cfg = self._config.clustering
        pipeline = TopicModelingPipeline(
            reducer=DimensionalityReducer(
                n_neighbors=cfg.n_neighbors,
                n_components=cfg.n_components or cfg.umap_n_components,
                min_dist=cfg.min_dist,
                seed=cfg.seed,
            ),
            clusterer=Clusterer(
                min_cluster_size=cfg.min_cluster_size,
                min_samples=cfg.min_samples,
                fallback_similarity_threshold=cfg.fallback_similarity_threshold,
                min_topic_size=cfg.min_topic_size,
            ),
            representer=TopicRepresenter(
                top_n_words=cfg.top_n_words,
                ngram_range=cfg.ngram_range,
            ),
            outlier_handler=OutlierHandler(),
            topic_merger=TopicMerger(cfg.nr_topics),
        )

        for bucket_id, idx_list in unique_buckets.items():
            idx = np.array(idx_list)
            items = [
                CorpusItem(
                    event_id=event_ids[i],
                    channel=channels[i],
                    message_id=message_ids[i],
                    text=texts[i] or "",
                    embedding=embeddings[i],
                    timestamp=timestamps[i],
                    bucket_id=bucket_ids[i],
                )
                for i in idx.tolist()
            ]
            result = pipeline.run(items)
            bucket_labels = result.labels
            bucket_probs = result.probabilities
            metric_parts.append(result.metrics)
            if result.strategy != "umap_hdbscan":
                strategy = result.strategy if strategy == "umap_hdbscan" else "mixed"

            mapped = np.where(bucket_labels == -1, -1, bucket_labels + cluster_offset)
            labels[idx] = mapped
            probs[idx] = bucket_probs

            for local_label, topic_meta in result.topic_metadata.items():
                public_label = int(local_label + cluster_offset)
                metadata[public_label] = topic_meta
            cluster_offset += len(
                {int(v) for v in bucket_labels.tolist() if int(v) >= 0}
            )

        metrics = {
            "mean_probability": round(float(np.mean(probs)) if len(probs) else 0.0, 6),
            "noise_ratio": round(float((labels == -1).sum() / max(1, len(labels))), 6),
            "bucket_count": len(unique_buckets),
            "bucket_metrics": metric_parts,
        }
        return labels, probs, strategy, metadata, metrics

    def _fallback_cluster_bucket(
        self,
        bucket_embeddings: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        if len(bucket_embeddings) == 0:
            return np.array([], dtype=int), np.array([], dtype=float)
        if len(bucket_embeddings) == 1:
            return np.array([0], dtype=int), np.array([1.0], dtype=float)

        normalized = self._normalize_embeddings(bucket_embeddings)
        threshold = self._config.clustering.fallback_similarity_threshold
        parent = list(range(len(normalized)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        similarity = normalized @ normalized.T
        for left in range(len(normalized)):
            for right in range(left + 1, len(normalized)):
                if float(similarity[left, right]) >= threshold:
                    union(left, right)

        root_to_label: dict[int, int] = {}
        labels = np.full(len(normalized), -1, dtype=int)
        next_label = 0
        for index in range(len(normalized)):
            root = find(index)
            if root not in root_to_label:
                root_to_label[root] = next_label
                next_label += 1
            labels[index] = root_to_label[root]

        probs = np.ones(len(normalized), dtype=float)
        for label in set(labels.tolist()):
            members = np.where(labels == label)[0]
            if len(members) <= 1:
                probs[members] = 1.0
                continue
            centroid = normalized[members].mean(axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm == 0:
                probs[members] = 0.75
                continue
            centroid = centroid / centroid_norm
            member_scores = normalized[members] @ centroid
            probs[members] = np.clip(member_scores, 0.55, 0.99)

        return labels, probs

    @staticmethod
    def _normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return embeddings / norms

    def _export_parquet(self, run_id: str) -> None:
        if self._db is None:
            return
        parquet_dir = Path(self._config.storage.parquet_dir)
        parquet_dir.mkdir(parents=True, exist_ok=True)
        out_path = parquet_dir / f"cluster_results_{run_id}.parquet"
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            cur = self._db.execute(
                "SELECT * FROM cluster_results WHERE run_id = ?", [run_id]
            )
            rows = cur.fetchall()
            if not rows:
                return
            col_names = [d[0] for d in cur.description]
            table = pa.table(
                {name: [r[i] for r in rows] for i, name in enumerate(col_names)}
            )
            pq.write_table(table, out_path)
            logger.info("exported parquet path=%s", out_path)
        except Exception:  # noqa: BLE001 - non-critical export
            logger.exception("parquet export failed run_id=%s", run_id)

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
