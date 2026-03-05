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
import duckdb
import hdbscan
import numpy as np
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

DUCKDB_INIT_SQL = """
CREATE TABLE IF NOT EXISTS message_embeddings (
    event_id VARCHAR PRIMARY KEY,
    channel VARCHAR NOT NULL,
    message_id BIGINT NOT NULL,
    text VARCHAR,
    embedding DOUBLE[],
    event_timestamp TIMESTAMP NOT NULL,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    clustered BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS cluster_results (
    id INTEGER PRIMARY KEY DEFAULT (nextval('cluster_results_seq')),
    event_id VARCHAR NOT NULL,
    channel VARCHAR NOT NULL,
    message_id BIGINT NOT NULL,
    cluster_id INTEGER NOT NULL,
    cluster_probability DOUBLE NOT NULL,
    bucket_id VARCHAR,
    run_id VARCHAR NOT NULL,
    run_timestamp TIMESTAMP NOT NULL,
    algo_version VARCHAR NOT NULL,
    window_start TIMESTAMP,
    window_end TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS cluster_results_seq START 1;

CREATE TABLE IF NOT EXISTS cluster_runs (
    run_id VARCHAR PRIMARY KEY,
    run_timestamp TIMESTAMP NOT NULL,
    algo_version VARCHAR NOT NULL,
    window_start TIMESTAMP,
    window_end TIMESTAMP,
    total_messages INTEGER,
    total_clustered INTEGER,
    total_noise INTEGER,
    n_clusters INTEGER,
    config_json VARCHAR,
    duration_seconds DOUBLE
);
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
    duckdb_connected: bool = False
    last_processed_at: Optional[str] = None
    last_clustering_at: Optional[str] = None
    last_error: Optional[str] = None


class TopicClustererService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._pool: Optional[asyncpg.Pool] = None
        self._duckdb: Optional[duckdb.DuckDBPyConnection] = None
        self._health = HealthState()
        self._input_validator = JsonSchemaValidator(
            config.schemas.preprocessed_message_path
        )
        self._stop_event = asyncio.Event()
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None
        self._clustering_task: Optional[asyncio.Task] = None

        logger.info(
            "loading sbert model name=%s device=%s",
            config.model.sbert_model,
            config.model.device,
        )
        self._sbert = SentenceTransformer(
            config.model.sbert_model, device=config.model.device
        )
        logger.info("sbert model loaded")

    async def start(self) -> None:
        await self._start_db()
        self._start_duckdb()
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
        if self._duckdb is not None:
            self._duckdb.close()
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

    def _start_duckdb(self) -> None:
        db_path = Path(self._config.storage.duckdb_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._duckdb = duckdb.connect(str(db_path))
        for statement in DUCKDB_INIT_SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                self._duckdb.execute(statement)
        self._health.duckdb_connected = True
        logger.info("duckdb initialized path=%s", db_path)

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
            "duckdb_connected": self._health.duckdb_connected,
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
        original_text = payload["payload"].get("original_text", "")

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

    # ── online ingest: compute embedding + store in DuckDB ──────────

    async def _ingest_once(self, context: MessageContext) -> ProcessingOutcome:
        if self._pool is None or self._duckdb is None:
            raise RuntimeError("service not initialized")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                should_process = await self._begin_processing(conn, context)
                if not should_process:
                    logger.info("duplicate event_id=%s", context.event_id)
                    MESSAGES_PROCESSED.labels(status="duplicate").inc()
                    return ProcessingOutcome.DUPLICATE

        text = context.original_text
        if not text or not text.strip():
            MESSAGES_PROCESSED.labels(status="skipped_empty").inc()
            async with self._pool.acquire() as conn:
                await conn.execute(
                    UPDATE_PROCESSED_COMPLETED_SQL, context.processing_event_id
                )
            return ProcessingOutcome.SUCCESS

        embedding = self._compute_embedding(text)

        self._duckdb.execute(
            """
            INSERT OR REPLACE INTO message_embeddings
                (event_id, channel, message_id, text, embedding, event_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                context.event_id,
                context.channel,
                context.message_id,
                text[:2000],
                embedding.tolist(),
                context.event_timestamp_dt,
            ],
        )

        unclustered = self._duckdb.execute(
            "SELECT count(*) FROM message_embeddings WHERE NOT clustered"
        ).fetchone()[0]
        BUFFER_SIZE.set(unclustered)

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

    def _compute_embedding(self, text: str) -> np.ndarray:
        return self._sbert.encode(
            text,
            normalize_embeddings=self._config.model.normalize_embeddings,
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
                await asyncio.get_event_loop().run_in_executor(
                    None, self._run_clustering
                )
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 - scheduler must not crash
                logger.exception("clustering run failed")
                CLUSTERING_RUNS.labels(status="error").inc()

    def _run_clustering(self) -> None:
        if self._duckdb is None:
            return

        rows = self._duckdb.execute(
            "SELECT event_id, channel, message_id, text, embedding, event_timestamp "
            "FROM message_embeddings WHERE NOT clustered "
            "ORDER BY event_timestamp"
        ).fetchall()

        if len(rows) < self._config.clustering.min_cluster_size:
            logger.info(
                "not enough unclustered messages count=%s min=%s",
                len(rows),
                self._config.clustering.min_cluster_size,
            )
            return

        logger.info("starting clustering run messages=%s", len(rows))
        start_time = time.monotonic()

        event_ids = [r[0] for r in rows]
        channels = [r[1] for r in rows]
        message_ids = [r[2] for r in rows]
        timestamps = [r[5] for r in rows]
        embeddings = np.array([r[4] for r in rows], dtype=np.float32)

        window_hours = self._config.clustering.window_hours
        bucket_ids = self._make_time_buckets(timestamps, window_hours)

        labels, probs = self._cluster_by_bucket(embeddings, bucket_ids)

        now_dt = datetime.now(timezone.utc)
        run_id = f"run_{now_dt.strftime('%Y%m%d_%H%M%S')}"
        algo_version = f"umap+hdbscan_v{self._config.model.version}"
        duration = time.monotonic() - start_time

        n_clusters = len(set(labels)) - (1 if -1 in set(labels) else 0)
        n_clustered = int((labels >= 0).sum())
        n_noise = int((labels == -1).sum())

        self._duckdb.execute(
            "INSERT INTO cluster_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                now_dt,
                algo_version,
                min(timestamps) if timestamps else None,
                max(timestamps) if timestamps else None,
                len(rows),
                n_clustered,
                n_noise,
                n_clusters,
                json.dumps({
                    "min_cluster_size": self._config.clustering.min_cluster_size,
                    "min_samples": self._config.clustering.min_samples,
                    "n_neighbors": self._config.clustering.n_neighbors,
                    "min_dist": self._config.clustering.min_dist,
                    "window_hours": window_hours,
                }),
                duration,
            ],
        )

        for i, eid in enumerate(event_ids):
            self._duckdb.execute(
                "INSERT INTO cluster_results "
                "(event_id, channel, message_id, cluster_id, cluster_probability, "
                "bucket_id, run_id, run_timestamp, algo_version, window_start, window_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    eid,
                    channels[i],
                    message_ids[i],
                    int(labels[i]),
                    float(probs[i]),
                    bucket_ids[i],
                    run_id,
                    now_dt,
                    algo_version,
                    min(timestamps) if timestamps else None,
                    max(timestamps) if timestamps else None,
                ],
            )

        self._duckdb.execute(
            "UPDATE message_embeddings SET clustered = true WHERE event_id IN "
            f"(SELECT unnest(?))",
            [event_ids],
        )

        self._export_parquet(run_id)

        CLUSTERING_RUNS.labels(status="success").inc()
        CLUSTERING_DURATION.observe(duration)
        CLUSTERS_FOUND.set(n_clusters)
        self._health.last_clustering_at = utc_now_iso()

        logger.info(
            "clustering complete run_id=%s n_clusters=%s clustered=%s noise=%s duration=%.1fs",
            run_id,
            n_clusters,
            n_clustered,
            n_noise,
            duration,
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
    ) -> tuple[np.ndarray, np.ndarray]:
        labels = np.full(len(embeddings), -1, dtype=int)
        probs = np.zeros(len(embeddings), dtype=float)

        unique_buckets: dict[str, list[int]] = {}
        for i, bid in enumerate(bucket_ids):
            unique_buckets.setdefault(bid, []).append(i)

        cluster_offset = 0
        cfg = self._config.clustering

        for bucket_id, idx_list in unique_buckets.items():
            idx = np.array(idx_list)
            if len(idx) < cfg.min_cluster_size:
                continue

            n_neighbors = min(cfg.n_neighbors, len(idx) - 1)
            if n_neighbors < 2:
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
            if n_clusters > 0:
                mapped = np.where(
                    bucket_labels == -1, -1, bucket_labels + cluster_offset
                )
                cluster_offset += n_clusters
            else:
                mapped = bucket_labels

            labels[idx] = mapped
            probs[idx] = bucket_probs

        return labels, probs

    def _export_parquet(self, run_id: str) -> None:
        if self._duckdb is None:
            return
        parquet_dir = Path(self._config.storage.parquet_dir)
        parquet_dir.mkdir(parents=True, exist_ok=True)
        out_path = parquet_dir / f"cluster_results_{run_id}.parquet"
        try:
            self._duckdb.execute(
                f"COPY (SELECT * FROM cluster_results WHERE run_id = ?) "
                f"TO '{out_path}' (FORMAT PARQUET)",
                [run_id],
            )
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
