"""Orchestration: batch, oneshot, and scheduled scoring modes."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import asyncpg
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from topic_scorer.config import AppConfig
from topic_scorer.features import (
    compute_per_run_stats,
    compute_raw_features,
    normalize_features,
)
from topic_scorer.metrics import (
    ERRORS_TOTAL,
    FEATURES_DURATION,
    LAST_RUN_TIMESTAMP,
    SCORED_TOPICS_TOTAL,
    SCORING_DURATION,
)
from topic_scorer.repository import TopicScorerRepository
from topic_scorer.schemas import ClusterFeatures, TopicScore
from topic_scorer.scoring import score_cluster

logger = logging.getLogger("topic_scorer")


class TopicScorerService:
    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._pool: Optional[asyncpg.Pool] = None
        self._repo: Optional[TopicScorerRepository] = None
        self._stop = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _init_pool(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=self._cfg.postgres.dsn(),
            min_size=self._cfg.postgres.min_size,
            max_size=self._cfg.postgres.max_size,
            command_timeout=self._cfg.postgres.command_timeout,
        )
        self._repo = TopicScorerRepository(self._pool, self._cfg.scoring)

    async def _close_pool(self) -> None:
        if self._pool:
            await self._pool.close()

    def request_stop(self) -> None:
        self._stop = True

    # ------------------------------------------------------------------
    # Metrics HTTP server (lightweight aiohttp)
    # ------------------------------------------------------------------

    async def _start_metrics_server(self) -> web.AppRunner:
        app = web.Application()

        async def _metrics(_req: web.Request) -> web.Response:
            return web.Response(
                body=generate_latest(),
                content_type=CONTENT_TYPE_LATEST,
            )

        async def _health(_req: web.Request) -> web.Response:
            return web.json_response({"status": "ok"})

        app.router.add_get("/metrics", _metrics)
        app.router.add_get("/health", _health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(
            runner,
            self._cfg.metrics.host,
            self._cfg.metrics.port,
        )
        await site.start()
        logger.info(
            "Metrics server listening on %s:%d",
            self._cfg.metrics.host,
            self._cfg.metrics.port,
        )
        return runner

    # ------------------------------------------------------------------
    # Core scoring logic
    # ------------------------------------------------------------------

    async def score_run(self, run_id: str, trigger: str) -> None:
        """Score all clusters in a single cluster run."""
        assert self._repo is not None
        cfg = self._cfg.scoring

        t_start = time.monotonic()
        logger.info("Starting scoring for run_id=%s trigger=%s", run_id, trigger)

        cluster_ids = await self._repo.get_cluster_ids(run_id)
        if not cluster_ids:
            logger.warning("No clusters found for run_id=%s", run_id)
            return

        # Determine time window midpoint for sub-window split
        now = datetime.now(tz=timezone.utc)
        mid_point = now  # will be overridden per-run when window info is available

        # Fetch all features in one round-trip
        try:
            all_features = await self._repo.fetch_all_features(
                run_id=run_id,
                mid_point=mid_point,
                history_days=cfg.history_window_days,
            )
        except Exception:
            logger.exception("Failed to fetch features for run_id=%s", run_id)
            ERRORS_TOTAL.labels(stage="features").inc()
            return

        if not all_features:
            logger.warning("No features fetched for run_id=%s", run_id)
            return

        # Compute raw features for all clusters
        raw_all: dict[str, dict[str, float]] = {}
        for cid, feat in all_features.items():
            t_feat = time.monotonic()
            try:
                raw_all[cid] = compute_raw_features(feat, cfg)
            except Exception:
                logger.exception("Feature computation failed for cluster=%s", cid)
                ERRORS_TOTAL.labels(stage="features").inc()
            finally:
                FEATURES_DURATION.observe(time.monotonic() - t_feat)

        # Per-run normalization stats
        per_run_stats = compute_per_run_stats(raw_all)

        # Score every cluster
        scores: List[TopicScore] = []
        errors = 0
        for cid, feat in all_features.items():
            if cid not in raw_all:
                continue
            try:
                norm = normalize_features(raw_all[cid], per_run_stats, cfg)
                ts = score_cluster(feat, raw_all[cid], norm, cfg)
                scores.append(ts)
                SCORED_TOPICS_TOTAL.labels(level=ts.importance_level).inc()
            except Exception:
                logger.exception("Scoring failed for cluster=%s", cid)
                ERRORS_TOTAL.labels(stage="scoring").inc()
                errors += 1

        # Persist
        try:
            await self._repo.persist_scores(scores)
        except Exception:
            logger.exception("Failed to persist scores for run_id=%s", run_id)
            ERRORS_TOTAL.labels(stage="persist").inc()
            errors += len(scores)
            scores = []

        duration = time.monotonic() - t_start
        SCORING_DURATION.labels(mode=trigger).observe(duration)
        LAST_RUN_TIMESTAMP.set(time.time())

        # Record audit row
        try:
            await self._repo.record_scoring_run(
                trigger=trigger,
                cluster_run_id=run_id,
                topics_scored=len(scores),
                errors=errors,
                duration_seconds=duration,
                scoring_version=cfg.version,
            )
        except Exception:
            logger.warning("Failed to record scoring run audit row", exc_info=True)

        logger.info(
            "Scoring complete: run_id=%s topics=%d errors=%d duration=%.2fs",
            run_id,
            len(scores),
            errors,
            duration,
        )

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def run_batch(self, run_id: Optional[str] = None) -> None:
        """Score all clusters in the latest (or given) run, then exit."""
        await self._init_pool()
        try:
            rid = run_id or await self._repo.get_latest_run_id()
            if not rid:
                logger.error("No cluster run found in database")
                return
            await self.score_run(rid, trigger="batch")
        finally:
            await self._close_pool()

    async def run_oneshot(self, run_id: str, public_cluster_id: str) -> None:
        """Score a single cluster on-demand."""
        await self._init_pool()
        try:
            assert self._repo is not None
            cfg = self._cfg.scoring
            now = datetime.now(tz=timezone.utc)
            feat = await self._repo.fetch_features_for_cluster(
                run_id=run_id,
                public_cluster_id=public_cluster_id,
                mid_point=now,
                history_days=cfg.history_window_days,
            )
            if feat is None:
                logger.error(
                    "Cluster %s not found in run %s", public_cluster_id, run_id
                )
                return
            raw = compute_raw_features(feat, cfg)
            # Single-cluster: no per-run normalization context — use identity [0,1] bounds
            per_run = {k: (0.0, max(v, 1.0)) for k, v in raw.items()}
            norm = normalize_features(raw, per_run, cfg)
            ts = score_cluster(feat, raw, norm, cfg)
            await self._repo.persist_scores([ts])
            SCORED_TOPICS_TOTAL.labels(level=ts.importance_level).inc()
            logger.info(
                "Oneshot score: cluster=%s score=%.4f level=%s",
                public_cluster_id,
                ts.importance_score,
                ts.importance_level,
            )
        finally:
            await self._close_pool()

    async def run_scheduled(self) -> None:
        """Periodic scoring: re-score the latest run every interval_seconds."""
        metrics_runner = None
        await self._init_pool()
        try:
            metrics_runner = await self._start_metrics_server()
            interval = self._cfg.scheduler.interval_seconds
            logger.info("Scheduled mode: interval=%ds", interval)
            while not self._stop:
                rid = await self._repo.get_latest_run_id()
                if rid:
                    await self.score_run(rid, trigger="scheduled")
                else:
                    logger.warning("No cluster run found, sleeping")
                await asyncio.sleep(interval)
        finally:
            await self._close_pool()
            if metrics_runner:
                await metrics_runner.cleanup()
