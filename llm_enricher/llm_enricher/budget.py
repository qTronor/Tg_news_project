from __future__ import annotations

import asyncio
import logging
from datetime import date, timezone
from datetime import datetime

import asyncpg

from llm_enricher.config import BudgetConfig
from llm_enricher.metrics import BUDGET_EXHAUSTED

logger = logging.getLogger("llm_enricher.budget")

_SUM_TODAY_SQL = """
SELECT COALESCE(SUM(cost_usd), 0.0) AS total
FROM llm_enrichments
WHERE created_at::date = CURRENT_DATE AND status = 'ok';
"""


class DailyBudgetTracker:
    """In-memory daily cost tracker, warm-started from Postgres."""

    def __init__(self, config: BudgetConfig) -> None:
        self._config = config
        self._today: date = date.today()
        self._cost_today: float = 0.0
        self._lock = asyncio.Lock()

    async def warm_start(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_SUM_TODAY_SQL)
        self._cost_today = float(row["total"])
        self._today = date.today()
        logger.info("Budget warm-start: cost_today=%.4f limit=%.2f", self._cost_today, self._config.daily_usd)

    def estimate_cost(self, tokens_input: int, tokens_output: int) -> float:
        cfg = self._config
        return (
            tokens_input / 1_000_000 * cfg.pricing_input_per_mtok
            + tokens_output / 1_000_000 * cfg.pricing_output_per_mtok
        )

    async def check_and_reserve(self, estimated_cost: float) -> bool:
        """Returns True if within budget, False if exhausted."""
        async with self._lock:
            today = date.today()
            if today != self._today:
                self._today = today
                self._cost_today = 0.0
            if self._cost_today + estimated_cost > self._config.daily_usd:
                BUDGET_EXHAUSTED.inc()
                logger.warning(
                    "Daily budget exhausted: cost_today=%.4f estimated=%.4f limit=%.2f",
                    self._cost_today,
                    estimated_cost,
                    self._config.daily_usd,
                )
                return False
            self._cost_today += estimated_cost
            return True

    async def record_actual(self, actual_cost: float, estimated_cost: float) -> None:
        """Adjust running total with the actual cost after the LLM call."""
        async with self._lock:
            self._cost_today += actual_cost - estimated_cost
