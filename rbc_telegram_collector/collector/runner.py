from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict
from uuid import UUID

import yaml

from collector.backfill import process_pending_validations, run_backfill_cycle
from collector.config import AppConfig, ChannelConfig
from collector.registry import RegistryChannel, RegistryStore
from collector.sinks.csv_sink import CsvSink
from collector.sinks.jsonl import JsonlSink
from collector.sinks.kafka_raw import KafkaRawSink
from collector.sources.telegram import TelegramChannelError, TelegramChannelSource


@dataclass(frozen=True)
class LiveChannelTarget:
    name: str
    channel_ref: str
    limit: int | None
    from_registry: bool
    channel_id: UUID | None = None


def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _resolve_window_start(lookback_days: int) -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=lookback_days - 1)


def _merge_live_channels(
    static_channels: list[ChannelConfig],
    registry_channels: list[RegistryChannel],
) -> list[LiveChannelTarget]:
    targets: list[LiveChannelTarget] = []
    seen: set[str] = set()

    for channel in static_channels:
        if not channel.enabled:
            continue
        normalized = channel.name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        targets.append(
            LiveChannelTarget(
                name=channel.name,
                channel_ref=str(channel.url) if channel.url else channel.name,
                limit=channel.limit,
                from_registry=False,
                channel_id=None,
            )
        )

    for channel in registry_channels:
        normalized = channel.name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        targets.append(
            LiveChannelTarget(
                name=channel.name,
                channel_ref=channel.channel_ref,
                limit=2000,
                from_registry=True,
                channel_id=channel.id,
            )
        )

    return targets


async def collect_once(cfg: AppConfig) -> Dict[str, int]:
    _setup_logging(cfg.logging.level)
    log = logging.getLogger("collector")

    data_dir = Path(cfg.output.data_dir)
    results: Dict[str, int] = {}
    effective_since = _resolve_window_start(cfg.collection.lookback_days)

    registry = RegistryStore(cfg.analytics_db)
    async with TelegramChannelSource(session_name="collector") as src:
        kafka_sink = KafkaRawSink(cfg.kafka) if cfg.kafka.enabled else None
        await registry.start()
        if kafka_sink is not None:
            await kafka_sink.start()

        try:
            validation_count = await process_pending_validations(
                source=src,
                registry=registry,
                cfg=cfg,
            )
            if validation_count:
                log.info("Pending channel validations processed=%s", validation_count)

            dynamic_channels = await registry.fetch_live_channels() if registry.enabled else []
            live_targets = _merge_live_channels(cfg.channels, dynamic_channels)
            live_results = await _collect_live_messages(
                cfg=cfg,
                source=src,
                registry=registry,
                kafka_sink=kafka_sink,
                data_dir=data_dir,
                effective_since=effective_since,
                channels=live_targets,
            )
            results.update(live_results)

            backfill_count = await run_backfill_cycle(
                source=src,
                registry=registry,
                kafka_sink=kafka_sink,
                cfg=cfg,
            )
            if backfill_count:
                log.info("Backfill jobs executed=%s", backfill_count)
        finally:
            await registry.stop()
            if kafka_sink is not None:
                await kafka_sink.stop()

    return results


async def _collect_live_messages(
    *,
    cfg: AppConfig,
    source: TelegramChannelSource,
    registry: RegistryStore,
    kafka_sink: KafkaRawSink | None,
    data_dir: Path,
    effective_since: date,
    channels: list[LiveChannelTarget],
) -> Dict[str, int]:
    log = logging.getLogger("collector.live")
    results: Dict[str, int] = {}

    for channel in channels:
        if "jsonl" in cfg.output.formats:
            jsonl_path = data_dir / f"{channel.name}.jsonl"
            if jsonl_path.exists():
                jsonl_path.unlink()
        if "csv" in cfg.output.formats:
            csv_path = data_dir / f"{channel.name}.csv"
            if csv_path.exists():
                csv_path.unlink()

        had_raw_data_before = (
            await registry.channel_has_raw_data(channel.name)
            if registry.enabled and channel.from_registry
            else False
        )

        log.info(
            "Collecting live channel=%s since=%s limit=%s source=%s",
            channel.name,
            effective_since,
            channel.limit,
            "registry" if channel.from_registry else "static",
        )

        try:
            items = [
                item
                async for item in source.iter_messages(
                    channel=channel.channel_ref,
                    since=effective_since,
                    min_id_exclusive=None,
                    limit=channel.limit,
                )
            ]
        except TelegramChannelError as exc:
            log.warning(
                "live_collection_failed channel=%s reason=%s detail=%s",
                channel.name,
                exc.reason,
                exc.message,
            )
            if registry.enabled and channel.from_registry and exc.permanent:
                await registry.mark_validation_failed(channel.channel_id, exc.message)
            results[channel.name] = 0
            continue

        if not items:
            log.info("No posts found in lookback window for channel=%s", channel.name)
            results[channel.name] = 0
            continue

        written = 0
        if "jsonl" in cfg.output.formats:
            written += JsonlSink(data_dir / f"{channel.name}.jsonl").write(items)

        if "csv" in cfg.output.formats:
            written += CsvSink(data_dir / f"{channel.name}.csv").write(items)

        published = 0
        if kafka_sink is not None:
            published = await kafka_sink.publish(items)

        if registry.enabled and channel.from_registry:
            await registry.mark_live_collected(channel.name, datetime.now(timezone.utc))
            if not had_raw_data_before and published > 0:
                log.info(
                    "first_data_available_emitted channel=%s emitted_at=%s",
                    channel.name,
                    datetime.now(timezone.utc).isoformat(),
                )

        log.info(
            "Done live channel=%s collected=%s stored=%s published_to_kafka=%s",
            channel.name,
            len(items),
            written,
            published,
        )
        results[channel.name] = len(items)

    return results


def run_collect(config_path: str) -> int:
    cfg = load_config(Path(config_path))
    results = asyncio.run(collect_once(cfg))
    total = sum(results.values())
    print("Collected:", results, "TOTAL:", total)
    return 0
