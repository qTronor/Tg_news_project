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
import hdbscan
import numpy as np
import torch
import umap
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sentence_transformers import SentenceTransformer

from topic_clusterer.config import AppConfig
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
        self._model_lock = asyncio.Lock()
        self._sbert = None
        self._device = self._resolve_device(config.model.device)
        logger.info(
            "topic model configured name=%s device=%s",
            config.model.sbert_model,
            self._device,
        )

    @staticmethod
    def _resolve_device(requested_device: str) -> str:
        normalized = (requested_device or "auto").strip().lower()
        if normalized == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if normalized.startswith("cuda") and not torch.cuda.is_available():
            logger.warning(
                "cuda requested for topic model but unavailable, falling back to cpu"
            )
            return "cpu"
        return normalized

    async def _ensure_model_loaded(self) -> None:
        if self._sbert is not None:
            return
        async with self._model_lock:
            if self._sbert is not None:
                return
            model_kwargs: dict[str, Any] = {
                "device": self._device,
            }
            if self._config.model.cache_dir:
                model_kwargs["cache_folder"] = self._config.model.cache_dir
            logger.info(
                "loading sbert model name=%s device=%s",
                self._config.model.sbert_model,
                self._device,
            )
            self._sbert = SentenceTransformer(
                self._config.model.sbert_model,
                **model_kwargs,
            )
            if self._device == "cuda" and self._config.model.use_float16:
                self._sbert.half()
            logger.info("sbert model loaded")

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
            body=generate_latest(), content_type=CONTENT_TYPE_LATEST
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
                (event_id, channel, message_id, text, embedding, trace_id, event_timestamp, clustered)
            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(
                (SELECT clustered FROM message_embeddings WHERE event_id = ?),
                0
            ))
            ON CONFLICT(event_id) DO UPDATE SET
                channel = excluded.channel,
                message_id = excluded.message_id,
                text = excluded.text,
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
        return self._sbert.encode(
            text,
            normalize_embeddings=self._config.model.normalize_embeddings,
            batch_size=self._config.model.batch_size,
            show_progress_bar=False,
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
                await loop.run_in_executor(
                    None, self._record_clustering_run_sqlite, batch
                )

    def _build_clustering_run(self) -> Optional[ClusteringRunBatch]:
        if self._db is None:
            return None

        rows = self._db.execute(
            "SELECT event_id, channel, message_id, text, embedding, trace_id, event_timestamp "
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
        timestamps = [
            parse_iso_datetime(ts) if isinstance(ts, str) else ts
            for ts in raw_timestamps
        ]
        embeddings = np.array(
            [json.loads(r[4] or "[]") for r in rows], dtype=np.float32
        )

        window_hours = self._config.clustering.window_hours
        bucket_ids = self._make_time_buckets(timestamps, window_hours)
        labels, probs, strategy = self._cluster_by_bucket(embeddings, bucket_ids)

        now_dt = datetime.now(timezone.utc)
        algo_version = f"{strategy}_v{self._config.model.version}"
        run_id = self._make_run_id(event_ids, algo_version)
        duration = time.monotonic() - start_time

        n_clusters = len(set(labels)) - (1 if -1 in set(labels) else 0)
        n_clustered = int((labels >= 0).sum())
        n_noise = int((labels == -1).sum())
        window_start = min(timestamps) if timestamps else None
        window_end = max(timestamps) if timestamps else None
        config_json = {
            "min_cluster_size": self._config.clustering.min_cluster_size,
            "min_samples": self._config.clustering.min_samples,
            "trigger_min_messages": self._config.clustering.trigger_min_messages,
            "n_neighbors": self._config.clustering.n_neighbors,
            "min_dist": self._config.clustering.min_dist,
            "window_hours": window_hours,
            "strategy": strategy,
        }

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
                    "name": self._config.model.sbert_model,
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
        self, embeddings: np.ndarray, bucket_ids: list[str]
    ) -> tuple[np.ndarray, np.ndarray, str]:
        labels = np.full(len(embeddings), -1, dtype=int)
        probs = np.zeros(len(embeddings), dtype=float)
        strategy = "umap_hdbscan"

        unique_buckets: dict[str, list[int]] = {}
        for i, bid in enumerate(bucket_ids):
            unique_buckets.setdefault(bid, []).append(i)

        cluster_offset = 0
        cfg = self._config.clustering

        for bucket_id, idx_list in unique_buckets.items():
            idx = np.array(idx_list)
            if len(idx) < cfg.min_cluster_size:
                fallback_labels, fallback_probs = self._fallback_cluster_bucket(
                    embeddings[idx]
                )
                labels[idx] = fallback_labels + cluster_offset
                probs[idx] = fallback_probs
                cluster_offset += len(set(fallback_labels))
                strategy = "similarity_fallback"
                continue

            n_neighbors = min(cfg.n_neighbors, len(idx) - 1)
            if n_neighbors < 2:
                fallback_labels, fallback_probs = self._fallback_cluster_bucket(
                    embeddings[idx]
                )
                labels[idx] = fallback_labels + cluster_offset
                probs[idx] = fallback_probs
                cluster_offset += len(set(fallback_labels))
                strategy = "similarity_fallback"
                continue

            umap_model = umap.UMAP(
                n_components=min(cfg.umap_n_components, len(idx) - 2),
                metric="cosine",
                n_neighbors=n_neighbors,
                min_dist=cfg.min_dist,
                random_state=42,
            )
            reduced = umap_model.fit_transform(embeddings[idx])

            hdb = hdbscan.HDBSCAN(
                min_cluster_size=cfg.min_cluster_size,
                min_samples=cfg.min_samples,
                cluster_selection_method="leaf",
                allow_single_cluster=False,
                prediction_data=True,
            )
            hdb.fit(reduced)

            bucket_labels = hdb.labels_
            bucket_probs = hdb.probabilities_
            n_clusters = len(set(bucket_labels)) - (
                1 if -1 in set(bucket_labels) else 0
            )
            if n_clusters <= 0:
                fallback_labels, fallback_probs = self._fallback_cluster_bucket(
                    embeddings[idx]
                )
                labels[idx] = fallback_labels + cluster_offset
                probs[idx] = fallback_probs
                cluster_offset += len(set(fallback_labels))
                strategy = "similarity_fallback"
                continue

            mapped = np.where(
                bucket_labels == -1, -1, bucket_labels + cluster_offset
            )
            cluster_offset += n_clusters
            labels[idx] = mapped
            probs[idx] = bucket_probs

            noise_positions = np.where(bucket_labels == -1)[0]
            if noise_positions.size > 0:
                fallback_labels, fallback_probs = self._fallback_cluster_bucket(
                    embeddings[idx][noise_positions]
                )
                labels[idx[noise_positions]] = fallback_labels + cluster_offset
                probs[idx[noise_positions]] = fallback_probs
                cluster_offset += len(set(fallback_labels))
                strategy = "mixed"

        return labels, probs, strategy

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
