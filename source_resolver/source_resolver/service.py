from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from source_resolver.config import AppConfig
from source_resolver.metrics import (
    PROPAGATION_EDGES_COUNT,
    SOURCE_CONFIDENCE,
    SOURCE_RESOLUTION_LATENCY,
    SOURCE_RESOLUTION_TOTAL,
)
from source_resolver.resolution import (
    ResolutionMessage,
    ResolvedSource,
    build_inferred_source,
    fallback_earliest_cluster_source,
    make_snippet,
    unknown_source,
)


logger = logging.getLogger("source_resolver")

SELECT_PENDING_CLUSTERS_SQL = """
WITH latest_run AS (
    SELECT run_id
    FROM cluster_runs_pg
    ORDER BY run_timestamp DESC
    LIMIT 1
)
SELECT DISTINCT ca.run_id, ca.cluster_id, ca.public_cluster_id
FROM cluster_assignments ca
JOIN latest_run lr ON lr.run_id = ca.run_id
LEFT JOIN cluster_source_resolutions csr_exact
    ON csr_exact.public_cluster_id = ca.public_cluster_id
   AND csr_exact.resolution_kind = 'exact'
LEFT JOIN cluster_source_resolutions csr_inferred
    ON csr_inferred.public_cluster_id = ca.public_cluster_id
   AND csr_inferred.resolution_kind = 'inferred'
WHERE ca.cluster_id >= 0
  AND (csr_exact.public_cluster_id IS NULL OR csr_inferred.public_cluster_id IS NULL)
ORDER BY ca.public_cluster_id
LIMIT $1;
"""

SELECT_CLUSTER_MESSAGES_SQL = """
SELECT
    ca.public_cluster_id,
    rm.event_id,
    rm.channel,
    rm.channel_id,
    rm.message_id,
    rm.message_date,
    rm.text,
    rm.reply_to_message_id,
    rm.forward_from_channel,
    rm.forward_from_channel_id,
    rm.forward_from_message_id,
    rm.forward_origin_type,
    pm.normalized_text,
    pm.tokens,
    pm.normalized_text_hash,
    pm.simhash64,
    pm.url_fingerprints,
    pm.primary_url_fingerprint
FROM cluster_assignments ca
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN preprocessed_messages pm ON pm.event_id = ca.event_id
WHERE ca.public_cluster_id = $1
ORDER BY rm.message_date ASC, rm.event_id ASC;
"""

SELECT_CLUSTER_ENTITIES_SQL = """
SELECT
    event_id,
    array_agg(DISTINCT lower(COALESCE(normalized_text, entity_text))) AS entities
FROM ner_results
WHERE event_id = ANY($1::varchar[])
GROUP BY event_id;
"""

SELECT_MESSAGE_BY_CHANNEL_ID_MESSAGE_ID_SQL = """
SELECT event_id, channel, message_id, message_date, text
FROM raw_messages
WHERE channel_id = $1 AND message_id = $2
ORDER BY message_date ASC
LIMIT 1;
"""

SELECT_MESSAGE_BY_CHANNEL_MESSAGE_ID_SQL = """
SELECT event_id, channel, message_id, message_date, text
FROM raw_messages
WHERE channel = $1 AND message_id = $2
ORDER BY message_date ASC
LIMIT 1;
"""

SELECT_URL_CANDIDATES_SQL = """
SELECT
    rm.event_id,
    rm.channel,
    rm.message_id,
    rm.message_date,
    rm.text,
    pm.primary_url_fingerprint
FROM preprocessed_messages pm
JOIN raw_messages rm ON rm.id = pm.raw_message_id
WHERE pm.primary_url_fingerprint = ANY($1::varchar[])
ORDER BY rm.message_date ASC, rm.event_id ASC;
"""

UPSERT_MESSAGE_SOURCE_SQL = """
INSERT INTO message_source_resolutions (
    message_event_id,
    message_channel,
    message_id,
    public_cluster_id,
    resolution_kind,
    source_type,
    source_confidence,
    source_event_id,
    source_channel,
    source_message_id,
    source_message_date,
    source_snippet,
    explanation_json,
    evidence_json,
    resolved_at
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14::jsonb, NOW()
)
ON CONFLICT (message_event_id, resolution_kind) DO UPDATE
SET source_type = EXCLUDED.source_type,
    source_confidence = EXCLUDED.source_confidence,
    source_event_id = EXCLUDED.source_event_id,
    source_channel = EXCLUDED.source_channel,
    source_message_id = EXCLUDED.source_message_id,
    source_message_date = EXCLUDED.source_message_date,
    source_snippet = EXCLUDED.source_snippet,
    explanation_json = EXCLUDED.explanation_json,
    evidence_json = EXCLUDED.evidence_json,
    resolved_at = NOW();
"""

UPSERT_CLUSTER_SOURCE_SQL = """
INSERT INTO cluster_source_resolutions (
    public_cluster_id,
    run_id,
    cluster_id,
    resolution_kind,
    source_type,
    source_confidence,
    source_event_id,
    source_channel,
    source_message_id,
    source_message_date,
    source_snippet,
    explanation_json,
    evidence_json,
    resolved_at
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, NOW()
)
ON CONFLICT (public_cluster_id, resolution_kind) DO UPDATE
SET source_type = EXCLUDED.source_type,
    source_confidence = EXCLUDED.source_confidence,
    source_event_id = EXCLUDED.source_event_id,
    source_channel = EXCLUDED.source_channel,
    source_message_id = EXCLUDED.source_message_id,
    source_message_date = EXCLUDED.source_message_date,
    source_snippet = EXCLUDED.source_snippet,
    explanation_json = EXCLUDED.explanation_json,
    evidence_json = EXCLUDED.evidence_json,
    resolved_at = NOW();
"""

DELETE_PROPAGATION_LINK_SQL = """
DELETE FROM message_propagation_links
WHERE child_event_id = $1;
"""

UPSERT_PROPAGATION_LINK_SQL = """
INSERT INTO message_propagation_links (
    public_cluster_id,
    resolution_kind,
    child_event_id,
    child_channel,
    child_message_id,
    parent_event_id,
    parent_channel,
    parent_message_id,
    link_type,
    link_confidence,
    explanation_json,
    evidence_json
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12::jsonb
)
ON CONFLICT (child_event_id) DO UPDATE
SET public_cluster_id = EXCLUDED.public_cluster_id,
    resolution_kind = EXCLUDED.resolution_kind,
    parent_event_id = EXCLUDED.parent_event_id,
    parent_channel = EXCLUDED.parent_channel,
    parent_message_id = EXCLUDED.parent_message_id,
    link_type = EXCLUDED.link_type,
    link_confidence = EXCLUDED.link_confidence,
    explanation_json = EXCLUDED.explanation_json,
    evidence_json = EXCLUDED.evidence_json,
    updated_at = NOW();
"""

COUNT_PROPAGATION_LINKS_SQL = """
SELECT count(*) FROM message_propagation_links;
"""


@dataclass(frozen=True)
class ClusterMessage(ResolutionMessage):
    channel_id: Optional[int]
    reply_to_message_id: Optional[int]
    forward_from_channel: Optional[str]
    forward_from_channel_id: Optional[int]
    forward_from_message_id: Optional[int]
    forward_origin_type: Optional[str]
    public_cluster_id: str


@dataclass
class HealthState:
    ready: bool = False
    postgres_connected: bool = False
    last_run_at: Optional[str] = None
    last_error: Optional[str] = None


class SourceResolverService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._health = HealthState()
        self._stop_event = asyncio.Event()
        self._web_runner: Optional[web.AppRunner] = None
        self._health_site: Optional[web.TCPSite] = None
        self._metrics_site: Optional[web.TCPSite] = None
        self._scheduler_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        await self._start_db()
        await self._start_http()
        self._scheduler_task = asyncio.create_task(self._resolution_scheduler())
        self._health.ready = True
        logger.info("service started")

    async def stop(self) -> None:
        self._health.ready = False
        self._stop_event.set()
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        if self._pool is not None:
            await self._pool.close()
        if self._web_runner is not None:
            await self._web_runner.cleanup()
        logger.info("service stopped")

    async def run(self) -> None:
        await self.start()
        try:
            await self._stop_event.wait()
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

    async def _start_http(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/metrics", self._handle_metrics)
        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()
        self._health_site = web.TCPSite(
            self._web_runner,
            self._config.health.host,
            self._config.health.port,
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
        return web.json_response(
            {
                "status": "ok" if self._health.ready else "starting",
                "ready": self._health.ready,
                "postgres_connected": self._health.postgres_connected,
                "last_run_at": self._health.last_run_at,
                "last_error": self._health.last_error,
            }
        )

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        return web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST)

    async def _resolution_scheduler(self) -> None:
        interval = self._config.scheduler.interval_seconds
        while not self._stop_event.is_set():
            try:
                await self._run_resolution_batch()
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - service-level guard
                logger.exception("resolution batch failed")
                self._health.last_error = str(exc)

    async def _run_resolution_batch(self) -> None:
        if self._pool is None:
            raise RuntimeError("service not initialized")

        async with self._pool.acquire() as conn:
            clusters = await conn.fetch(
                SELECT_PENDING_CLUSTERS_SQL,
                self._config.scheduler.cluster_batch_size,
            )

        for cluster in clusters:
            await self._resolve_cluster(
                run_id=cluster["run_id"],
                cluster_id=cluster["cluster_id"],
                public_cluster_id=cluster["public_cluster_id"],
            )

        self._health.last_run_at = datetime.utcnow().isoformat() + "Z"

    async def _resolve_cluster(
        self,
        *,
        run_id: str,
        cluster_id: int,
        public_cluster_id: str,
    ) -> None:
        if self._pool is None:
            raise RuntimeError("service not initialized")

        started = time.monotonic()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                messages = await self._fetch_cluster_messages(conn, public_cluster_id)
                if not messages:
                    return

                url_candidates = await self._fetch_url_candidates(
                    conn,   
                    \
                    [m.primary_url_fingerprint for m in messages if m.primary_url_fingerprint],
                )
                by_channel_msg = {(m.channel, m.message_id): m for m in messages}
                by_channel_id_msg = {
                    (m.channel_id, m.message_id): m
                    for m in messages
                    if m.channel_id is not None
                }

                exact_rows: list[ResolvedSource] = []
                for idx, message in enumerate(messages):
                    exact = await self._resolve_exact_source(
                        conn,
                        message,
                        by_channel_msg,
                        by_channel_id_msg,
                        url_candidates,
                    )
                    inferred = self._resolve_inferred_source(message, messages[:idx])
                    exact_rows.append(exact)

                    await self._upsert_message_resolution(conn, message, "exact", exact)
                    await self._upsert_message_resolution(conn, message, "inferred", inferred)
                    await self._upsert_propagation_link(conn, message, exact, inferred)

                    for kind, resolution in (("exact", exact), ("inferred", inferred)):
                        SOURCE_RESOLUTION_TOTAL.labels(
                            target="message",
                            resolution_kind=kind,
                            source_type=resolution.source_type,
                        ).inc()
                        SOURCE_CONFIDENCE.observe(resolution.confidence)

                cluster_exact = self._select_cluster_exact_source(exact_rows)
                cluster_inferred = fallback_earliest_cluster_source(
                    messages[0],
                    self._config.resolution.earliest_cluster_confidence,
                )

                await self._upsert_cluster_resolution(
                    conn,
                    public_cluster_id,
                    run_id,
                    cluster_id,
                    "exact",
                    cluster_exact,
                )
                await self._upsert_cluster_resolution(
                    conn,
                    public_cluster_id,
                    run_id,
                    cluster_id,
                    "inferred",
                    cluster_inferred,
                )

                for kind, resolution in (("exact", cluster_exact), ("inferred", cluster_inferred)):
                    SOURCE_RESOLUTION_TOTAL.labels(
                        target="cluster",
                        resolution_kind=kind,
                        source_type=resolution.source_type,
                    ).inc()
                    SOURCE_CONFIDENCE.observe(resolution.confidence)

                edge_count = await conn.fetchval(COUNT_PROPAGATION_LINKS_SQL)
                PROPAGATION_EDGES_COUNT.set(edge_count or 0)

        SOURCE_RESOLUTION_LATENCY.observe(time.monotonic() - started)

    async def _fetch_cluster_messages(
        self,
        conn: asyncpg.Connection,
        public_cluster_id: str,
    ) -> list[ClusterMessage]:
        rows = await conn.fetch(SELECT_CLUSTER_MESSAGES_SQL, public_cluster_id)
        if not rows:
            return []

        event_ids = [row["event_id"] for row in rows]
        entities_rows = await conn.fetch(SELECT_CLUSTER_ENTITIES_SQL, event_ids)
        entities_map = {
            row["event_id"]: {entity for entity in (row["entities"] or []) if entity}
            for row in entities_rows
        }

        messages: list[ClusterMessage] = []
        for row in rows:
            messages.append(
                ClusterMessage(
                    event_id=row["event_id"],
                    channel=row["channel"],
                    message_id=row["message_id"],
                    message_date=row["message_date"],
                    text=row["text"] or "",
                    normalized_text=row["normalized_text"] or "",
                    tokens=list(row["tokens"] or []),
                    normalized_text_hash=row["normalized_text_hash"],
                    simhash64=row["simhash64"],
                    url_fingerprints=list(row["url_fingerprints"] or []),
                    primary_url_fingerprint=row["primary_url_fingerprint"],
                    entities=entities_map.get(row["event_id"], set()),
                    channel_id=row["channel_id"],
                    reply_to_message_id=row["reply_to_message_id"],
                    forward_from_channel=row["forward_from_channel"],
                    forward_from_channel_id=row["forward_from_channel_id"],
                    forward_from_message_id=row["forward_from_message_id"],
                    forward_origin_type=row["forward_origin_type"],
                    public_cluster_id=row["public_cluster_id"],
                )
            )
        return messages

    async def _fetch_url_candidates(
        self,
        conn: asyncpg.Connection,
        fingerprints: list[str],
    ) -> dict[str, list[asyncpg.Record]]:
        unique = sorted({fingerprint for fingerprint in fingerprints if fingerprint})
        if not unique:
            return {}
        rows = await conn.fetch(SELECT_URL_CANDIDATES_SQL, unique)
        candidates: dict[str, list[asyncpg.Record]] = {}
        for row in rows:
            candidates.setdefault(row["primary_url_fingerprint"], []).append(row)
        return candidates

    async def _resolve_exact_source(
        self,
        conn: asyncpg.Connection,
        message: ClusterMessage,
        by_channel_msg: dict[tuple[str, int], ClusterMessage],
        by_channel_id_msg: dict[tuple[int, int], ClusterMessage],
        url_candidates: dict[str, list[asyncpg.Record]],
    ) -> ResolvedSource:
        if (
            message.forward_from_channel_id is not None
            and message.forward_from_message_id is not None
        ):
            candidate = by_channel_id_msg.get(
                (message.forward_from_channel_id, message.forward_from_message_id)
            )
            if candidate is None:
                row = await conn.fetchrow(
                    SELECT_MESSAGE_BY_CHANNEL_ID_MESSAGE_ID_SQL,
                    message.forward_from_channel_id,
                    message.forward_from_message_id,
                )
                candidate = self._row_to_message(row)
            if candidate is not None and candidate.message_date <= message.message_date:
                return ResolvedSource(
                    source_type="exact_forward",
                    confidence=1.0,
                    source_event_id=candidate.event_id,
                    source_channel=candidate.channel,
                    source_message_id=candidate.message_id,
                    source_message_date=candidate.message_date,
                    source_snippet=make_snippet(candidate.text),
                    explanation={"summary": "Telegram forward metadata contains original channel and message id"},
                    evidence={
                        "forward_from_channel_id": message.forward_from_channel_id,
                        "forward_from_message_id": message.forward_from_message_id,
                        "forward_origin_type": message.forward_origin_type,
                    },
                )

        if message.reply_to_message_id is not None:
            candidate = by_channel_msg.get((message.channel, message.reply_to_message_id))
            if candidate is None:
                row = await conn.fetchrow(
                    SELECT_MESSAGE_BY_CHANNEL_MESSAGE_ID_SQL,
                    message.channel,
                    message.reply_to_message_id,
                )
                candidate = self._row_to_message(row)
            if candidate is not None and candidate.message_date <= message.message_date:
                return ResolvedSource(
                    source_type="exact_reply",
                    confidence=0.97,
                    source_event_id=candidate.event_id,
                    source_channel=candidate.channel,
                    source_message_id=candidate.message_id,
                    source_message_date=candidate.message_date,
                    source_snippet=make_snippet(candidate.text),
                    explanation={"summary": "Telegram reply metadata points to a specific earlier message"},
                    evidence={"reply_to_message_id": message.reply_to_message_id},
                )

        if message.primary_url_fingerprint:
            for row in url_candidates.get(message.primary_url_fingerprint, []):
                if row["event_id"] == message.event_id:
                    continue
                if row["message_date"] > message.message_date:
                    continue
                return ResolvedSource(
                    source_type="exact_url",
                    confidence=0.92,
                    source_event_id=row["event_id"],
                    source_channel=row["channel"],
                    source_message_id=row["message_id"],
                    source_message_date=row["message_date"],
                    source_snippet=make_snippet(row["text"] or ""),
                    explanation={"summary": "Strict primary URL fingerprint match linked the message to an earlier publication"},
                    evidence={"primary_url_fingerprint": message.primary_url_fingerprint},
                )

        return unknown_source("No strict Telegram metadata or strict URL match found")

    def _resolve_inferred_source(
        self,
        message: ClusterMessage,
        earlier_messages: list[ClusterMessage],
    ) -> ResolvedSource:
        if not earlier_messages:
            return unknown_source("No earlier messages exist in the cluster")

        candidates = [
            build_inferred_source(
                message,
                candidate,
                self._config.resolution.inferred_threshold,
                self._config.resolution.quote_min_chars,
            )
            for candidate in earlier_messages
        ]
        candidates.sort(
            key=lambda item: (
                -item.confidence,
                self._sort_datetime(item.source_message_date),
            )
        )
        best = candidates[0]
        if best.confidence >= self._config.resolution.inferred_threshold:
            return best
        return fallback_earliest_cluster_source(
            earlier_messages[0],
            self._config.resolution.earliest_cluster_confidence,
        )

    def _select_cluster_exact_source(
        self,
        exact_rows: list[ResolvedSource],
    ) -> ResolvedSource:
        concrete = [
            row
            for row in exact_rows
            if row.source_event_id is not None and row.source_type != "unknown"
        ]
        if not concrete:
            return unknown_source("No exact source found for messages in the cluster")
        concrete.sort(
            key=lambda row: (
                self._sort_datetime(row.source_message_date),
                -row.confidence,
            )
        )
        return concrete[0]

    async def _upsert_message_resolution(
        self,
        conn: asyncpg.Connection,
        message: ClusterMessage,
        resolution_kind: str,
        resolution: ResolvedSource,
    ) -> None:
        await conn.execute(
            UPSERT_MESSAGE_SOURCE_SQL,
            message.event_id,
            message.channel,
            message.message_id,
            message.public_cluster_id,
            resolution_kind,
            resolution.source_type,
            resolution.confidence,
            resolution.source_event_id,
            resolution.source_channel,
            resolution.source_message_id,
            resolution.source_message_date,
            resolution.source_snippet,
            json.dumps(resolution.explanation),
            json.dumps(resolution.evidence),
        )

    async def _upsert_cluster_resolution(
        self,
        conn: asyncpg.Connection,
        public_cluster_id: str,
        run_id: str,
        cluster_id: int,
        resolution_kind: str,
        resolution: ResolvedSource,
    ) -> None:
        await conn.execute(
            UPSERT_CLUSTER_SOURCE_SQL,
            public_cluster_id,
            run_id,
            cluster_id,
            resolution_kind,
            resolution.source_type,
            resolution.confidence,
            resolution.source_event_id,
            resolution.source_channel,
            resolution.source_message_id,
            resolution.source_message_date,
            resolution.source_snippet,
            json.dumps(resolution.explanation),
            json.dumps(resolution.evidence),
        )

    async def _upsert_propagation_link(
        self,
        conn: asyncpg.Connection,
        message: ClusterMessage,
        exact: ResolvedSource,
        inferred: ResolvedSource,
    ) -> None:
        chosen_kind = None
        chosen = None
        if exact.source_event_id is not None and exact.source_event_id != message.event_id:
            chosen_kind = "exact"
            chosen = exact
        elif inferred.source_event_id is not None and inferred.source_event_id != message.event_id:
            chosen_kind = "inferred"
            chosen = inferred

        if chosen is None or chosen_kind is None:
            await conn.execute(DELETE_PROPAGATION_LINK_SQL, message.event_id)
            return

        await conn.execute(
            UPSERT_PROPAGATION_LINK_SQL,
            message.public_cluster_id,
            chosen_kind,
            message.event_id,
            message.channel,
            message.message_id,
            chosen.source_event_id,
            chosen.source_channel,
            chosen.source_message_id,
            chosen.source_type,
            chosen.confidence,
            json.dumps(chosen.explanation),
            json.dumps(chosen.evidence),
        )

    @staticmethod
    def _row_to_message(row: Optional[asyncpg.Record]) -> Optional[ResolutionMessage]:
        if row is None:
            return None
        return ResolutionMessage(
            event_id=row["event_id"],
            channel=row["channel"],
            message_id=row["message_id"],
            message_date=row["message_date"],
            text=row["text"] or "",
            normalized_text=row["text"] or "",
            tokens=[],
            normalized_text_hash=None,
            simhash64=None,
            url_fingerprints=[],
            primary_url_fingerprint=None,
            entities=set(),
        )

    @staticmethod
    def _sort_datetime(value: Optional[datetime]) -> float:
        if value is None:
            return float("-inf")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
