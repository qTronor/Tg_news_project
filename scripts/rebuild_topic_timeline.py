from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import asyncpg

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics_api"))

from analytics_api.config import load_config  # noqa: E402
from analytics_api.service import AnalyticsApiService, _parse_iso_datetime  # noqa: E402
from analytics_api.topic_evolution import normalize_bucket_size  # noqa: E402


async def _run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    service = AnalyticsApiService(config)
    pool = await asyncpg.create_pool(
        dsn=config.postgres.dsn(),
        min_size=1,
        max_size=1,
        command_timeout=config.postgres.command_timeout,
    )
    try:
        async with pool.acquire() as conn:
            from_dt, to_dt = _resolve_window(args.from_dt, args.to_dt)
            cluster_ids = [args.cluster_id] if args.cluster_id else await _latest_cluster_ids(conn)
            for cluster_id in cluster_ids:
                result = await service._rebuild_topic_timeline(
                    conn,
                    cluster_id,
                    from_dt,
                    to_dt,
                    args.bucket,
                )
                logging.info("rebuilt cluster_id=%s result=%s", cluster_id, result)
    finally:
        await pool.close()


async def _latest_cluster_ids(conn: asyncpg.Connection) -> list[str]:
    run_id = await conn.fetchval(
        "SELECT run_id FROM cluster_runs_pg ORDER BY run_timestamp DESC LIMIT 1;"
    )
    if run_id is None:
        return []
    rows = await conn.fetch(
        """
        SELECT DISTINCT public_cluster_id
        FROM cluster_assignments
        WHERE run_id = $1 AND cluster_id >= 0
        ORDER BY public_cluster_id ASC;
        """,
        run_id,
    )
    return [row["public_cluster_id"] for row in rows]


def _resolve_window(from_raw: Optional[str], to_raw: Optional[str]) -> tuple[datetime, datetime]:
    if from_raw and to_raw:
        return _parse_iso_datetime(from_raw), _parse_iso_datetime(to_raw)
    to_dt = datetime.now(timezone.utc)
    return to_dt - timedelta(days=30), to_dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild materialized topic timeline/evolution layer")
    parser.add_argument("--config", type=Path, default=Path("analytics_api/config.yaml"))
    parser.add_argument("--cluster-id", help="Public cluster id. If omitted, rebuilds latest run clusters.")
    parser.add_argument("--bucket", default="1h", help="Bucket size: 15m, 1h, 1d")
    parser.add_argument("--from", dest="from_dt", help="Inclusive ISO timestamp")
    parser.add_argument("--to", dest="to_dt", help="Inclusive ISO timestamp")
    args = parser.parse_args()
    try:
        args.bucket = normalize_bucket_size(args.bucket)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
