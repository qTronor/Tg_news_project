from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from aiohttp import web
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from paper_detector.config import AppConfig
from paper_detector.detector import detect
from paper_detector.repository import insert_paper

logger = logging.getLogger("paper_detector")

MESSAGES_PROCESSED = Counter("paper_detector_messages_total", "Total preprocessed messages read", ["result"])
PROCESSING_LATENCY = Histogram("paper_detector_processing_seconds", "Processing latency")


class PaperDetectorService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._ready = False

    async def start(self) -> None:
        await self._start_db()
        await asyncio.gather(
            self._run_http(self._config.service.port),
            self._run_metrics(self._config.service.metrics_port),
            self._run_consumer(),
        )

    async def _start_db(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn,
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
        self._ready = True
        logger.info("PostgreSQL pool ready")

    async def _run_http(self, port: int) -> None:
        app = web.Application()
        app.router.add_get("/health", self._health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._config.service.host, port)
        await site.start()
        logger.info("HTTP on :%d", port)

    async def _run_metrics(self, port: int) -> None:
        app = web.Application()
        app.router.add_get("/metrics", self._metrics)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._config.service.host, port)
        await site.start()
        logger.info("Metrics on :%d", port)

    async def _health(self, _: web.Request) -> web.Response:
        status = "ok" if self._ready else "starting"
        return web.json_response({"status": status})

    async def _metrics(self, _: web.Request) -> web.Response:
        return web.Response(
            body=generate_latest(),
            content_type=CONTENT_TYPE_LATEST,
        )

    async def _run_consumer(self) -> None:
        cfg = self._config.kafka
        consumer = AIOKafkaConsumer(
            cfg.input_topic,
            bootstrap_servers=cfg.bootstrap_servers,
            group_id=cfg.consumer_group,
            auto_offset_reset=cfg.auto_offset_reset,
            value_deserializer=lambda b: json.loads(b.decode()),
            enable_auto_commit=True,
        )
        producer = AIOKafkaProducer(
            bootstrap_servers=cfg.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        await consumer.start()
        await producer.start()
        logger.info("Consumer started on %s", cfg.input_topic)
        try:
            async for msg in consumer:
                await self._handle(msg.value, producer)
        finally:
            await consumer.stop()
            await producer.stop()

    async def _handle(self, message: dict, producer: AIOKafkaProducer) -> None:
        start = time.monotonic()
        try:
            is_paper, source_type, source_url = detect(message)
            if not is_paper:
                MESSAGES_PROCESSED.labels(result="skipped").inc()
                return

            now = datetime.now(timezone.utc).isoformat()
            source_message_id = str(message.get("message_id") or message.get("id") or "")
            source_channel = str(message.get("channel") or message.get("source_channel") or "")
            telegram_file_id = (message.get("media") or {}).get("file_id")

            paper_id = await insert_paper(
                self._pool,
                source_message_id=source_message_id,
                source_channel=source_channel,
                source_url=source_url,
                source_type=source_type,
                telegram_file_id=telegram_file_id,
                detected_at=now,
            )

            if paper_id is None:
                logger.debug("Duplicate paper skipped: %s", source_url)
                MESSAGES_PROCESSED.labels(result="duplicate").inc()
                return

            event = {
                "event_id": str(uuid.uuid4()),
                "paper_db_id": paper_id,
                "source_message_id": source_message_id,
                "source_channel": source_channel,
                "source_url": source_url,
                "source_type": source_type,
                "detected_at": now,
                "telegram_file_id": telegram_file_id,
                "metadata": {},
            }
            await producer.send_and_wait(self._config.kafka.output_topic, event)
            MESSAGES_PROCESSED.labels(result="detected").inc()
            logger.info("Paper detected: %s type=%s", source_url or "file", source_type)

        except Exception as exc:
            logger.exception("Error processing message: %s", exc)
            MESSAGES_PROCESSED.labels(result="error").inc()
            await self._send_dlq(message, exc, producer)
        finally:
            PROCESSING_LATENCY.observe(time.monotonic() - start)

    async def _send_dlq(self, message: dict, exc: Exception, producer: AIOKafkaProducer) -> None:
        try:
            dlq_msg = {"original": message, "error": str(exc), "service": "paper_detector"}
            await producer.send_and_wait(self._config.kafka.dlq_topic, dlq_msg)
        except Exception:
            logger.exception("Failed to send DLQ message")
