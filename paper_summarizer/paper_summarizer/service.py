from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from aiohttp import web
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from paper_summarizer.config import AppConfig
from paper_summarizer.mistral_client import MistralClient
from paper_summarizer.prompt import PROMPT_VERSION, build_prompt, strip_forbidden_fields
from paper_summarizer.repository import insert_summary

logger = logging.getLogger("paper_summarizer")

SUMMARIES_TOTAL = Counter("paper_summarizer_summaries_total", "Summaries", ["status"])
SUMMARY_LATENCY = Histogram("paper_summarizer_summary_seconds", "Summary latency")


class PaperSummarizerService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._mistral: Optional[MistralClient] = None
        self._ready = False

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn,
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
        self._mistral = MistralClient(self._config.mistral)
        self._ready = True
        await asyncio.gather(
            self._run_http(self._config.service.port),
            self._run_metrics(self._config.service.metrics_port),
            self._run_consumer(),
        )

    async def _run_http(self, port: int) -> None:
        app = web.Application()
        app.router.add_get("/health", lambda r: web.json_response({"status": "ok" if self._ready else "starting"}))
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, self._config.service.host, port).start()

    async def _run_metrics(self, port: int) -> None:
        app = web.Application()
        app.router.add_get("/metrics", lambda r: web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST))
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, self._config.service.host, port).start()

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
        try:
            async for msg in consumer:
                await self._handle(msg.value, producer)
        finally:
            await consumer.stop()
            await producer.stop()

    async def _handle(self, event: dict, producer: AIOKafkaProducer) -> None:
        start = time.monotonic()
        paper_id = event.get("paper_id")
        text_for_summary = event.get("text_for_summary")

        if not text_for_summary:
            logger.warning("No text for summary, paper_id=%s", paper_id)
            SUMMARIES_TOTAL.labels(status="skipped").inc()
            return

        try:
            prompt = build_prompt(text_for_summary)
            raw = await self._mistral.complete(prompt)

            try:
                summary_json = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON from Mistral: {exc}") from exc

            summary_json = strip_forbidden_fields(summary_json)
            short_summary = summary_json.get("short_summary")

            await insert_summary(
                self._pool,
                paper_id=paper_id,
                model_name=self._config.mistral.model,
                prompt_version=PROMPT_VERSION,
                summary_json=summary_json,
                short_summary=short_summary,
            )

            out_event = {
                "paper_id": paper_id,
                "model_name": self._config.mistral.model,
                "prompt_version": PROMPT_VERSION,
                "summary_json": summary_json,
                "short_summary": short_summary,
                "summarized_at": datetime.now(timezone.utc).isoformat(),
            }
            await producer.send_and_wait(self._config.kafka.output_topic, out_event)
            SUMMARIES_TOTAL.labels(status="ok").inc()
            logger.info("Summary created for paper_id=%s", paper_id)

        except Exception as exc:
            logger.exception("Error summarizing paper %s: %s", paper_id, exc)
            SUMMARIES_TOTAL.labels(status="error").inc()
            try:
                dlq_msg = {"original": event, "error": str(exc), "service": "paper_summarizer"}
                await producer.send_and_wait(self._config.kafka.dlq_topic, dlq_msg)
            except Exception:
                logger.exception("DLQ send failed")
        finally:
            SUMMARY_LATENCY.observe(time.monotonic() - start)
