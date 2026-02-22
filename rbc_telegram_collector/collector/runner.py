from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Dict

import yaml

from collector.config import AppConfig
from collector.state import StateStore
from collector.sources.telegram import TelegramChannelSource
from collector.sinks.jsonl import JsonlSink
from collector.sinks.csv_sink import CsvSink


def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def collect_once(cfg: AppConfig) -> Dict[str, int]:
    _setup_logging(cfg.logging.level)
    log = logging.getLogger("collector")

    data_dir = Path(cfg.output.data_dir)
    state_dir = Path(cfg.output.state_dir)
    state = StateStore(state_dir / "state.json")
    last_ids = state.load()

    results: Dict[str, int] = {}

    async with TelegramChannelSource(session_name="collector") as src:
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
            # Используем URL если он указан, иначе используем name как username
            channel_identifier = str(ch_cfg.url) if ch_cfg.url else ch_cfg.name
            min_id = last_ids.get(channel)
            if min_id is None:
                effective_since: Optional[date] = ch_cfg.since
            else:
                effective_since = (datetime.now(timezone.utc) - timedelta(days=3)).date()

            log.info(
                "Collecting channel=%s since=%s min_id=%s limit=%s",
                channel,
                effective_since,
                min_id,
                ch_cfg.limit,
            )

            items = []
            max_id_seen: Optional[int] = None

            async for item in src.iter_messages(
                channel=channel_identifier,
                since=effective_since,
                min_id_exclusive=min_id,
                limit=ch_cfg.limit,
            ):
                items.append(item)
                max_id_seen = item.message_id if (max_id_seen is None or item.message_id > max_id_seen) else max_id_seen

            if not items:
                log.info("No new posts for channel=%s", channel)
                results[channel] = 0
                continue

            written = 0
            if "jsonl" in cfg.output.formats:
                sink = JsonlSink(data_dir / f"{channel}.jsonl")
                written += sink.write(items)

            if "csv" in cfg.output.formats:
                sink = CsvSink(data_dir / f"{channel}.csv")
                written += sink.write(items)

            if max_id_seen is not None:
                state.set_last_id(channel, max_id_seen)

            log.info("Done channel=%s written=%s last_id=%s", channel, written, max_id_seen)
            results[channel] = written

    return results


def run_collect(config_path: str) -> int:
    cfg = load_config(Path(config_path))
    results = asyncio.run(collect_once(cfg))
    total = sum(results.values())
    print("Collected:", results, "TOTAL:", total)
    return 0
