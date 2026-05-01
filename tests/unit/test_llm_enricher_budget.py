"""Tests for DailyBudgetTracker."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_enricher.budget import DailyBudgetTracker
from llm_enricher.config import BudgetConfig


def _tracker(daily_usd: float = 1.0) -> DailyBudgetTracker:
    cfg = BudgetConfig(
        daily_usd=daily_usd,
        pricing_input_per_mtok=2.0,
        pricing_output_per_mtok=6.0,
    )
    return DailyBudgetTracker(cfg)


@pytest.mark.asyncio
async def test_within_budget_allowed():
    tracker = _tracker(daily_usd=1.0)
    allowed = await tracker.check_and_reserve(estimated_cost=0.01)
    assert allowed is True


@pytest.mark.asyncio
async def test_over_budget_rejected():
    tracker = _tracker(daily_usd=0.001)
    allowed = await tracker.check_and_reserve(estimated_cost=0.01)
    assert allowed is False


@pytest.mark.asyncio
async def test_cumulative_budget_exhausted():
    tracker = _tracker(daily_usd=0.05)
    await tracker.check_and_reserve(0.03)
    allowed = await tracker.check_and_reserve(0.03)
    assert allowed is False


@pytest.mark.asyncio
async def test_warm_start_loads_from_db():
    tracker = _tracker(daily_usd=5.0)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=MagicMock(
        __aenter__=AsyncMock(return_value=MagicMock(
            fetchrow=AsyncMock(return_value={"total": 3.50})
        )),
        __aexit__=AsyncMock(return_value=False),
    ))
    await tracker.warm_start(pool)
    assert tracker._cost_today == pytest.approx(3.50)


def test_estimate_cost():
    tracker = _tracker()
    cost = tracker.estimate_cost(tokens_input=1_000_000, tokens_output=500_000)
    # 1M * $2/M + 0.5M * $6/M = $2 + $3 = $5
    assert cost == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_record_actual_adjusts_total():
    tracker = _tracker(daily_usd=10.0)
    await tracker.check_and_reserve(0.10)
    await tracker.record_actual(actual_cost=0.07, estimated_cost=0.10)
    # cost_today should be 0.07 now
    assert tracker._cost_today == pytest.approx(0.07)
