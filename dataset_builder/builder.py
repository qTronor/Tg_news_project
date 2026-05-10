"""Core dataset building logic (standalone CLI, not imported by analytics API)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from dataset_builder.config import AppConfig
from analytics_api.analytics_api.annotation import (
    build_dataset,
    export_dataset,
)

logger = logging.getLogger("dataset_builder")


class DatasetBuilder:
    """High-level wrapper that delegates to the shared annotation module."""

    def __init__(self, pool: asyncpg.Pool, config: AppConfig) -> None:
        self._pool = pool
        self._config = config

    async def build(
        self,
        name: str,
        description: str,
        window_start: datetime,
        window_end: datetime,
        channels: Optional[list[str]] = None,
        created_by: Optional[str] = None,
        min_word_count: Optional[int] = None,
        dedup_strategy: Optional[str] = None,
    ) -> str:
        cfg = self._config.builder
        return await build_dataset(
            pool=self._pool,
            name=name,
            description=description,
            window_start=window_start,
            window_end=window_end,
            channels=channels or [],
            min_word_count=min_word_count if min_word_count is not None else cfg.min_word_count,
            dedup_strategy=dedup_strategy or cfg.dedup_strategy,
            languages=cfg.supported_languages,
            created_by=created_by,
        )

    async def export(
        self,
        version_id: str,
        fmt: str = "jsonl",
        output_path: Optional[str] = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            content_type, filename, data = await export_dataset(conn, version_id, fmt)

        path = output_path or filename
        with open(path, "wb") as f:
            f.write(data)
        logger.info("exported %s → %s (%d bytes)", fmt, path, len(data))
