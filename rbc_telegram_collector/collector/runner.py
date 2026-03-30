from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Dict

import yaml

from collector.config import AppConfig
from collector.sources.telegram import TelegramChannelSource
from collector.sinks.csv_sink import CsvSink
from collector.sinks.jsonl import JsonlSink
from collector.sinks.kafka_raw import KafkaRawSink


def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _resolve_window_start(lookback_days: int) -> date:
    return (datetime.now(timezone.utc).date() - timedelta(days=lookback_days - 1))


async def collect_once(cfg: AppConfig) -> Dict[str, int]:
    _setup_logging(cfg.logging.level)
    log = logging.getLogger("collector")

    data_dir = Path(cfg.output.data_dir)
    results: Dict[str, int] = {}
    effective_since = _resolve_window_start(cfg.collection.lookback_days)

    async with TelegramChannelSource(session_name="collector") as src:
        kafka_sink = KafkaRawSink(cfg.kafka) if cfg.kafka.enabled else None
        if kafka_sink is not None:
            await kafka_sink.start()

        try:
            for ch_cfg in cfg.channels:
                if not ch_cfg.enabled:
                    continue

                channel = ch_cfg.name
                if "jsonl" in cfg.output.formats:
                    jsonl_path = data_dir / f"{channel}.jsonl"
                    if jsonl_path.exists():
                        jsonl_path.unlink()
                if "csv" in cfg.output.formats:
                    csv_path = data_dir / f"{channel}.csv"
                    if csv_path.exists():
                        csv_path.unlink()

                channel_identifier = str(ch_cfg.url) if ch_cfg.url else ch_cfg.name

                log.info(
                    "Collecting channel=%s since=%s limit=%s",
                    channel,
                    effective_since,
                    ch_cfg.limit,
                )

                items = []
                async for item in src.iter_messages(
                    channel=channel_identifier,
                    since=effective_since,
                    min_id_exclusive=None,
                    limit=ch_cfg.limit,
                ):
                    items.append(item)

                if not items:
                    log.info("No posts found in lookback window for channel=%s", channel)
                    results[channel] = 0
                    continue

                written = 0
                if "jsonl" in cfg.output.formats:
                    written += JsonlSink(data_dir / f"{channel}.jsonl").write(items)

                if "csv" in cfg.output.formats:
                    written += CsvSink(data_dir / f"{channel}.csv").write(items)

                published = 0
                if kafka_sink is not None:
                    published = await kafka_sink.publish(items)

                log.info(
                    "Done channel=%s collected=%s stored=%s published_to_kafka=%s",
                    channel,
                    len(items),
                    written,
                    published,
                )
                results[channel] = len(items)
        finally:
            if kafka_sink is not None:
                await kafka_sink.stop()

    return results


def run_collect(config_path: str) -> int:
    cfg = load_config(Path(config_path))
    results = asyncio.run(collect_once(cfg))
    total = sum(results.values())
    print("Collected:", results, "TOTAL:", total)
    return 0
