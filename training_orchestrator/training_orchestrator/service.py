from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import asyncpg
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from training_orchestrator.config import AppConfig

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

from analytics_api.mlops import TrainingOrchestrator  # noqa: E402


logger = logging.getLogger("training_orchestrator")

JOBS_TOTAL = Counter("training_orchestrator_jobs_total", "Jobs processed by orchestrator", ["status", "task_type"])
TICK_DURATION = Histogram("training_orchestrator_tick_duration_seconds", "Polling tick duration")


class TrainingOrchestratorService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
        self._runner: Optional[web.AppRunner] = None
        self._stop = asyncio.Event()
        self._orchestrator: Optional[TrainingOrchestrator] = None

    async def run(self) -> None:
        await self.start()
        try:
            while not self._stop.is_set():
                await self.tick()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._config.service.poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.stop()

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._config.postgres.dsn(),
            min_size=self._config.postgres.min_size,
            max_size=self._config.postgres.max_size,
            command_timeout=self._config.postgres.command_timeout,
        )
        self._orchestrator = TrainingOrchestrator(self._pool)
        app = web.Application()
        app.router.add_get("/health", self._health)
        app.router.add_get("/metrics", self._metrics)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, self._config.api.host, self._config.api.port).start()
        logger.info("training orchestrator started on %s:%s", self._config.api.host, self._config.api.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        if self._pool is not None:
            await self._pool.close()

    async def tick(self) -> None:
        if self._pool is None or self._orchestrator is None:
            return
        with TICK_DURATION.time():
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, task_type
                    FROM training_jobs
                    WHERE status='queued'
                    ORDER BY created_at ASC
                    LIMIT $1
                    """,
                    self._config.service.max_jobs_per_tick,
                )
            for row in rows:
                result = await self._orchestrator.run_job(str(row["id"]))
                JOBS_TOTAL.labels(status=result["status"], task_type=row["task_type"]).inc()

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": self._config.service_name})

    async def _metrics(self, request: web.Request) -> web.Response:
        return web.Response(body=generate_latest(), content_type=CONTENT_TYPE_LATEST)
