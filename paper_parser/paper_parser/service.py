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

from paper_parser.config import AppConfig
from paper_parser.repository import insert_paper_text, update_paper
from paper_parser.parsers.arxiv import fetch_arxiv_metadata
from paper_parser.parsers.openreview import fetch_openreview_metadata
from paper_parser.parsers.pdf import download_and_extract_text

logger = logging.getLogger("paper_parser")

PAPERS_PROCESSED = Counter("paper_parser_papers_total", "Papers processed", ["status"])
PARSE_LATENCY = Histogram("paper_parser_parse_seconds", "Parsing latency")


class PaperParserService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._ready = False

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn,
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
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
        logger.info("HTTP on :%d", port)

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
        paper_id = event.get("paper_db_id")
        source_type = event.get("source_type", "")
        source_url = event.get("source_url")
        source_message_id = event.get("source_message_id", "")
        source_channel = event.get("source_channel", "")
        cfg = self._config.service

        title, authors, abstract, published_at = None, [], None, None
        full_text: Optional[str] = None
        extraction_method = "none"
        parsing_status = "failed"

        try:
            if source_type == "arxiv" and source_url:
                meta = await fetch_arxiv_metadata(source_url, cfg.http_timeout_seconds)
                if meta:
                    title, authors, abstract, published_at = meta.title, meta.authors, meta.abstract, meta.published_at
                    if meta.pdf_url:
                        full_text = await download_and_extract_text(meta.pdf_url, cfg.http_timeout_seconds)
                        extraction_method = "arxiv_pdf"

            elif source_type == "openreview" and source_url:
                meta = await fetch_openreview_metadata(source_url, cfg.http_timeout_seconds)
                if meta:
                    title, authors, abstract = meta.title, meta.authors, meta.abstract
                    if meta.pdf_url:
                        full_text = await download_and_extract_text(meta.pdf_url, cfg.http_timeout_seconds)
                        extraction_method = "openreview_pdf"

            elif source_type == "pdf_url" and source_url:
                full_text = await download_and_extract_text(source_url, cfg.http_timeout_seconds)
                extraction_method = "pdf_url"

            if title and abstract:
                parsing_status = "parsed"
            elif title or abstract or full_text:
                parsing_status = "partial"
            else:
                parsing_status = "failed"

            full_text_available = bool(full_text)
            text_length = len(full_text) if full_text else None

            if paper_id:
                await update_paper(
                    self._pool,
                    paper_id=paper_id,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    published_at=published_at,
                    parsing_status=parsing_status,
                )
                if full_text and text_length and text_length > cfg.max_full_text_chars:
                    await insert_paper_text(
                        self._pool,
                        paper_id=paper_id,
                        full_text=full_text,
                        extraction_method=extraction_method,
                    )

            text_for_summary = _build_summary_text(abstract, full_text, cfg.summary_text_chars)

            out_event = {
                "paper_id": paper_id,
                "source_message_id": source_message_id,
                "source_channel": source_channel,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "text_for_summary": text_for_summary,
                "full_text_available": full_text_available,
                "text_length": text_length,
                "source_type": source_type,
                "source_url": source_url,
                "parsing_status": parsing_status,
                "parsed_at": datetime.now(timezone.utc).isoformat(),
            }
            await producer.send_and_wait(self._config.kafka.output_topic, out_event)
            PAPERS_PROCESSED.labels(status=parsing_status).inc()
            logger.info("Paper parsed: %s status=%s", paper_id, parsing_status)

        except Exception as exc:
            logger.exception("Error parsing paper %s: %s", paper_id, exc)
            PAPERS_PROCESSED.labels(status="error").inc()
            try:
                dlq_msg = {"original": event, "error": str(exc), "service": "paper_parser"}
                await producer.send_and_wait(self._config.kafka.dlq_topic, dlq_msg)
            except Exception:
                logger.exception("DLQ send failed")
        finally:
            PARSE_LATENCY.observe(time.monotonic() - start)


def _build_summary_text(abstract: Optional[str], full_text: Optional[str], max_chars: int) -> Optional[str]:
    parts = []
    if abstract:
        parts.append(abstract)
    if full_text:
        remaining = max_chars - len(abstract or "")
        if remaining > 0:
            parts.append(full_text[:remaining])
    return "\n\n".join(parts) if parts else None
