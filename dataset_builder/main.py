"""
dataset_builder CLI

Usage examples:
  python -m dataset_builder build \
      --name ru-telegram-topics-v1 \
      --start 2026-01-01 --end 2026-04-30 \
      --channels rbc_news,tass_agency \
      --min-words 5

  python -m dataset_builder export \
      --id <uuid> --format jsonl --out dataset.jsonl

  python -m dataset_builder stats --id <uuid>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

import asyncpg

from dataset_builder.config import load_config
from dataset_builder.builder import DatasetBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("dataset_builder.cli")


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def cmd_build(args: argparse.Namespace, builder: DatasetBuilder) -> None:
    channels = [c.strip() for c in args.channels.split(",") if c.strip()] if args.channels else []
    version_id = await builder.build(
        name=args.name,
        description=args.description or "",
        window_start=_parse_dt(args.start),
        window_end=_parse_dt(args.end),
        channels=channels,
        min_word_count=args.min_words,
        dedup_strategy=args.dedup,
    )
    print(f"Dataset built: {version_id}")


async def cmd_export(args: argparse.Namespace, builder: DatasetBuilder) -> None:
    await builder.export(
        version_id=args.id,
        fmt=args.format,
        output_path=args.out,
    )


async def cmd_stats(args: argparse.Namespace, pool: asyncpg.Pool) -> None:
    from analytics_api.analytics_api.annotation import SELECT_ANNOTATION_STATS_SQL
    import uuid
    vid = uuid.UUID(args.id) if args.id else None
    async with pool.acquire() as conn:
        rows = await conn.fetch(SELECT_ANNOTATION_STATS_SQL, vid)
    for row in rows:
        print(json.dumps(dict(row), default=str, ensure_ascii=False, indent=2))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Dataset builder CLI")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command")

    # build
    p_build = sub.add_parser("build")
    p_build.add_argument("--name", required=True)
    p_build.add_argument("--description", default="")
    p_build.add_argument("--start", required=True, help="ISO datetime, e.g. 2026-01-01")
    p_build.add_argument("--end", required=True, help="ISO datetime, e.g. 2026-04-30")
    p_build.add_argument("--channels", default="", help="Comma-separated channel names")
    p_build.add_argument("--min-words", type=int, default=5)
    p_build.add_argument("--dedup", default="event_id", choices=["event_id", "text_hash", "none"])

    # export
    p_export = sub.add_parser("export")
    p_export.add_argument("--id", required=True, help="Dataset version UUID")
    p_export.add_argument(
        "--format", default="jsonl",
        choices=["csv", "jsonl", "octis", "huggingface"],
    )
    p_export.add_argument("--out", default=None, help="Output file path")

    # stats
    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--id", default=None, help="Dataset version UUID (all if omitted)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cfg = load_config(args.config)
    pool = await asyncpg.create_pool(
        dsn=cfg.postgres.dsn(),
        min_size=cfg.postgres.min_size,
        max_size=cfg.postgres.max_size,
    )
    try:
        builder = DatasetBuilder(pool, cfg)
        if args.command == "build":
            await cmd_build(args, builder)
        elif args.command == "export":
            await cmd_export(args, builder)
        elif args.command == "stats":
            await cmd_stats(args, pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
